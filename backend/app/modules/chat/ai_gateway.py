import logging
import re
import datetime
from typing import List, Dict, Any, Optional
import httpx
from app.core.config import settings
from app.modules.connector.tools import execute_tool
from app.modules.connector.commands import command_queue_service
from app.modules.connector.client import connector_client
from app.middleware.tenant_context import TenantContext

logger = logging.getLogger("connector_ai.ai_gateway")

# Unicode digit translation table covering Devanagari, Gujarati, Bengali, Tamil, Telugu, Kannada -> ASCII 0-9
INDIAN_DIGIT_MAP = str.maketrans(
    "०१२३४५६७८९"  # Devanagari (Hindi / Marathi)
    "૦૧૨૩૪૫૬૭૮૯"  # Gujarati
    "০১২৩৪৫৬৭৮৯"  # Bengali
    "௦௧௨௩௪௫௬௭௮௯"  # Tamil
    "౦౧౨౩౪౫౬౭౮౯"  # Telugu
    "೦೧೨೩೪೫೬೭೮೯", # Kannada
    "0123456789" * 6,
)


def normalize_indian_numerals(text: str) -> str:
    """Normalizes regional Unicode digits and Indian number multipliers (hazar, lakh, crore) into standard numerals."""
    if not text:
        return ""
    normalized = text.translate(INDIAN_DIGIT_MAP)

    # Convert spoken multipliers (e.g., "50 hazar", "50 हज़ार", "2.5 lakh", "2 लाख", "1 crore")
    def _replace_multiplier(match: re.Match) -> str:
        val = float(match.group(1))
        unit = match.group(2).lower()
        if unit in ("crore", "cr", "करोड़", "કરોડ", "कोटी"):
            return str(int(val * 10000000))
        if unit in ("lakh", "lac", "lakhs", "लाख", "લાખ"):
            return str(int(val * 100000))
        if unit in ("hazar", "hazaar", "thousand", "k", "हज़ार", "हजार", "હજાર"):
            return str(int(val * 1000))
        return match.group(0)

    normalized = re.sub(
        r"(\d+(?:\.\d+)?)\s*(crore|cr|करोड़|કરોડ|कोटी|lakh|lac|lakhs|लाख|લાખ|hazar|hazaar|thousand|k|हज़ार|हजार|હજાર)\b",
        _replace_multiplier,
        normalized,
        flags=re.IGNORECASE,
    )
    return normalized


def detect_language_and_script(text: str) -> Dict[str, str]:
    """
    Zero-Click Automatic Language & Script Detector (Auto-LID).
    Detects Unicode scripts (Devanagari, Gujarati, Marathi, Tamil, Telugu, Bengali, Kannada)
    and distinguishes Roman Hinglish from Pure English using lexical tokenization.
    """
    sample = (text or "").strip()
    if not sample:
        return {"code": "en-IN", "name": "English", "voice": "en-IN-PrabhatNeural"}

    # 1. Check Regional Indian Unicode Scripts
    if re.search(r"[\u0A80-\u0AFF]", sample):
        return {"code": "gu-IN", "name": "Gujarati", "voice": "gu-IN-NiranjanNeural"}
    if re.search(r"[\u0980-\u09FF]", sample):
        return {"code": "bn-IN", "name": "Bengali", "voice": "bn-IN-BashkarNeural"}
    if re.search(r"[\u0B80-\u0BFF]", sample):
        return {"code": "ta-IN", "name": "Tamil", "voice": "ta-IN-ValluvarNeural"}
    if re.search(r"[\u0C00-\u0C7F]", sample):
        return {"code": "te-IN", "name": "Telugu", "voice": "te-IN-MohanNeural"}
    if re.search(r"[\u0C80-\u0CFF]", sample):
        return {"code": "kn-IN", "name": "Kannada", "voice": "kn-IN-GaganNeural"}

    # 2. Check Devanagari (Distinguish Marathi vs Hindi)
    if re.search(r"[\u0900-\u097F]", sample):
        marathi_markers = {"आहे", "करा", "सांगा", "माझ्या", "साठी", "बनवा", "किती", "पावती", "कंपनी", "द्या", "माहिती"}
        tokens = set(re.findall(r"[\u0900-\u097F]+", sample))
        if tokens.intersection(marathi_markers):
            return {"code": "mr-IN", "name": "Marathi", "voice": "mr-IN-ManoharNeural"}
        return {"code": "hi-IN", "name": "Hindi", "voice": "hi-IN-MadhurNeural"}

    # 3. Roman Script Analysis: Distinguish Roman Hinglish vs Pure English
    roman_tokens = set(re.findall(r"[a-zA-Z]+", sample.lower()))
    hinglish_markers = {
        "hai", "hain", "kya", "kaise", "karo", "karein", "bana", "bna", "banao",
        "daal", "kaat", "dikhao", "batao", "batayein", "ke", "liye", "ko", "ka",
        "ki", "mera", "mere", "apna", "kitna", "kitne", "abhi", "chal", "raha",
        "rha", "rahi", "nahi", "nhi", "bhai", "namaste", "ji", "kripya", "hazar",
        "hazaar", "lakh", "chahiye", "mujhe", "mein", "naya", "bhejo", "dekho",
        "aur", "se", "par", "pr", "bhi", "toh", "kuch", "koi", "isko", "usko",
        "kr", "krna", "karna", "pata", "pta", "chalega", "ek", "sirf", "kab",
        "kyu", "kyon", "kahan", "kaun", "kon", "tum", "aap", "hum", "hamara",
        "jabab", "jawab", "sawal", "baat", "bata", "bol", "bolo", "puche", "aa",
    }
    if roman_tokens.intersection(hinglish_markers):
        return {"code": "hinglish", "name": "Hinglish", "voice": "hi-IN-MadhurNeural"}

    return {"code": "en-IN", "name": "English", "voice": "en-IN-PrabhatNeural"}


def extract_voucher_entities(text: str) -> Dict[str, Any]:
    """Dynamically extracts party name, normalized amount, voucher type, GST rate, and IGST mode across English, Hinglish, and Indian scripts."""
    clean_raw = (text or "").strip().strip('"\'`')
    normalized_text = normalize_indian_numerals(clean_raw)
    lower_norm = normalized_text.lower()

    # 1. Extract GST Rate if explicitly mentioned (e.g. "12% gst", "@ 5%", "28 percent")
    gst_rate = 18.0
    rate_match = re.search(r"(\d{1,2}(?:\.\d+)?)\s*(?:%|percent|प्रतिशत|टक्के)\b", normalized_text, re.IGNORECASE)
    if rate_match:
        try:
            parsed_rate = float(rate_match.group(1))
            if 0.0 <= parsed_rate <= 40.0:
                gst_rate = parsed_rate
        except ValueError:
            pass

    # Remove percentage expression before extracting currency amount so "18%" isn't mistaken for ₹18
    amount_search_text = re.sub(r"\d{1,2}(?:\.\d+)?\s*(?:%|percent|प्रतिशत|टक्के)\b", "", normalized_text, flags=re.IGNORECASE)

    # 2. Dynamic Amount Extraction
    amt = None
    std_match = re.search(r"(?:rs\.?|inr|₹)?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?", amount_search_text, re.IGNORECASE)
    if std_match:
        try:
            whole = std_match.group(1).replace(",", "")
            dec = std_match.group(2)
            amt = float(f"{whole}.{dec}" if dec else whole)
        except (ValueError, TypeError):
            amt = None

    # 3. Dynamic Company & Party Name Extraction
    party = None
    target_company = None
    blacklist = {
        "sales", "purchase", "receipt", "payment", "bill", "invoice", "voucher",
        "tally", "me", "mein", "karo", "banao", "do", "de", "bana do", "bna do",
        "kaat do", "daal do", "create", "generate", "make", "new", "for", "to",
        "dikhao", "dekho", "view", "show", "mera", "apna",
    }

    # Structured Compound Pattern: "[Company] me [Party] ko/ke liye [Amount]..."
    comp_party_match = re.search(
        r"^(?:in\s+)?(.*?)\s+(?:me|mein|में)\s+(.*?)\s+(?:ko|ke\s+liye|को|के\s+लिए)\s+(?:\d|rs|inr|₹)",
        normalized_text,
        re.IGNORECASE,
    )
    if comp_party_match:
        c_cand = comp_party_match.group(1).strip()
        p_cand = comp_party_match.group(2).strip()
        c_cand = re.sub(r"^(?:mere|apne|my|the|in)\s+", "", c_cand, flags=re.IGNORECASE).strip()
        p_cand = re.sub(r"^(?:bhai|bro|please|plz|ek|naya|new)\s+", "", p_cand, flags=re.IGNORECASE).strip()
        if len(c_cand) >= 3 and c_cand.lower() not in blacklist:
            target_company = c_cand
        if len(p_cand) >= 2 and p_cand.lower() not in blacklist:
            party = p_cand.title() if re.match(r"^[A-Za-z0-9\s&.\'-]+$", p_cand) else p_cand

    if not party:
        patterns = [
            # Hinglish / Hindi / Marathi / Gujarati postpositions: "[Party] ke liye / ko / se"
            r"([^\d,₹]+?)\s+(?:ke\s+liye|ko|se|के\s+लिए|को|से|माटे|માટે|साठी)\s+(?:\d|rs|inr|₹)",
            # English prepositions: "for / to / from [Party] of / worth / amount / ₹ / digits"
            r"(?:for|to|from)\s+([A-Za-z0-9\s&.\'-]+?)\s+(?:of|amount|worth|rs\.?|inr|₹|\d)",
            # Trailing party: "invoice/bill/receipt for/to/from/ke liye [Party]"
            r"(?:bill|invoice|voucher|receipt|इनवॉइस|बिल|रसीद|બિલ)\s+(?:for|to|from|ke\s+liye|ko|के\s+लिए|माटे|માટે|साठी)\s+([^\d,₹]+?)(?:\s+(?:bna|bana|create|generate|daal|karo|kaat|बना|બનાવો|बनवा)|$)",
        ]

        for pat in patterns:
            m = re.search(pat, normalized_text, re.IGNORECASE)
            if m:
                candidate = m.group(1).strip()
                candidate = re.sub(
                    r"^(?:bhai|bro|please|plz|ek|naya|new|create|generate|daal|make|sales|receipt|purchase|invoice|bill|voucher|for|to|from|कृपया|एक|नया)\s+",
                    "",
                    candidate,
                    flags=re.IGNORECASE,
                ).strip()
                # If candidate still contains "me" or "mein", split company
                if " me " in f" {candidate.lower()} ":
                    parts = re.split(r"\s+(?:me|mein)\s+", candidate, flags=re.IGNORECASE, maxsplit=1)
                    if len(parts) == 2 and not target_company:
                        target_company = parts[0].strip()
                        candidate = parts[1].strip()

                if len(candidate) >= 2 and candidate.lower() not in blacklist:
                    party = candidate.title() if re.match(r"^[A-Za-z0-9\s&.\'-]+$", candidate) else candidate
                    break

    # 4. Target Company extraction if not yet extracted
    comp_patterns = [
        r"(?:company\s+|in\s+company\s+|कंपनी\s+)?([A-Za-z0-9\s&.\'-]+?)\s+(?:me|mein|में|मा|માં)\s+(?:voucher|bill|invoice|receipt|payment|entry|bna|bana|create|daal|karo)",
        r"(?:company\s+|in\s+company\s+|कंपनी\s+)?([A-Za-z0-9\s&.\'-]+?)\s+(?:ke\s+andar|ke\s+khate\s+me)\b",
    ]
    for cp in comp_patterns:
        cm = re.search(cp, normalized_text, re.IGNORECASE)
        if cm:
            c_cand = cm.group(1).strip()
            c_cand = re.sub(r"^(?:mere|apne|my|the|in)\s+", "", c_cand, flags=re.IGNORECASE).strip()
            if len(c_cand) >= 3 and c_cand.lower() not in blacklist and c_cand.lower() not in {"tally", "ctrlbooks", "system"}:
                target_company = c_cand
                break

    # 5. Detect Voucher Type (Sales, Receipt, Payment, Purchase, Credit/Debit Note, Contra, Journal)
    v_type = "Sales"
    if any(w in lower_norm for w in ["receipt", "payment mila", "jama hua", "received", "receive", "रसीद", "पावती"]):
        v_type = "Receipt"
    elif any(w in lower_norm for w in ["payment", "diya", "bhugtan", "paid", "भुगतान", "पेमेंट"]):
        v_type = "Payment"
    elif any(w in lower_norm for w in ["purchase", "khareed", "vendor bill", "खरीद"]):
        v_type = "Purchase"
    elif any(w in lower_norm for w in ["credit note", "sales return", "क्रेडिट"]):
        v_type = "Credit Note"
    elif any(w in lower_norm for w in ["debit note", "purchase return", "डेबिट"]):
        v_type = "Debit Note"
    elif any(w in lower_norm for w in ["contra", "cash deposit", "bank transfer", "कॉन्ट्रा"]):
        v_type = "Contra"
    elif any(w in lower_norm for w in ["journal", "adjustment", "जर्नल"]):
        v_type = "Journal"

    # 6. Detect Inter-State IGST vs Intra-State CGST+SGST
    is_igst = any(w in lower_norm for w in ["igst", "interstate", "inter-state", "out of state", "आईजीएसटी"])

    return {
        "amount": amt,
        "party": party,
        "voucher_type": v_type,
        "gst_rate": gst_rate,
        "is_igst": is_igst,
        "target_company": target_company,
    }


def _resolve_caller_identity(
    user_meta: Optional[Dict[str, Any]],
    ctx: TenantContext,
    active_company: str,
) -> Dict[str, Any]:
    """Dynamically resolves caller identity from authenticated session metadata or tenant context without hardcoded personas."""
    meta = user_meta or {}
    raw_uid = str(ctx.user_id or "authenticated_user")
    default_email = raw_uid if "@" in raw_uid else f"{raw_uid}@{active_company.lower().replace(' ', '')[:16] or 'tenant'}.ctrlbooks.com"

    return {
        "name": (meta.get("user_name") or "").strip() or f"Authorized User ({raw_uid})",
        "email": (meta.get("user_email") or "").strip() or default_email,
        "phone": (meta.get("user_phone") or "").strip() or "Session Verified",
        "tally_port": meta.get("tally_port"),
        "company_id": meta.get("company_id"),
        "connector_token": meta.get("connector_token"),
    }


def _discover_sample_party(active_company: str) -> str:
    """Dynamically discovers an active party ledger for the given company from the live queue, or returns a generic placeholder."""
    try:
        queued = command_queue_service.list_queued_commands()
        for item in reversed(queued):
            if item.get("company") == active_company:
                p_name = item.get("payload", {}).get("payload", {}).get("party_ledger")
                if p_name:
                    return p_name
    except Exception:
        pass
    return f"{active_company} Customer"


def _estimate_token_usage(messages: List[Dict[str, str]], completion_text: str) -> Dict[str, int]:
    """Dynamically calculates token usage based on actual input history and generated response length."""
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    completion_chars = len(completion_text or "")
    prompt_tokens = max(8, round(prompt_chars / 3.8))
    completion_tokens = max(8, round(completion_chars / 3.8))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _sanitize_brand_identity(text: str) -> str:
    """Ensures third-party model names and Pvt/Demo Ltd suffixes never appear in responses."""
    if not text:
        return text
    cleaned = re.sub(
        r"\b(Mistral\s*AI|Ministral(?:-\d+b(?:-\d+)?)?|Open-Mistral(?:-Nemo)?|Mistral(?:-Small|-Large|-7B)?|OpenAI|ChatGPT|GPT-4o?(?:-mini)?)\b",
        "CtrlBooks AI Assistant (PatwatoliAI Sub-Assistant)",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\bCtrlBooks\s+(?:Pvt\.?\s*Ltd\.?|Demo\s+Ltd\.?)\b", "CtrlBooks", cleaned, flags=re.IGNORECASE)
    return cleaned


def _is_ctrlbooks_domain_query(text: str, messages: List[Dict[str, str]]) -> bool:
    """
    Strictly validates whether the user query belongs to the CtrlBooks / Tally Prime / GST / Accounting / Support domain.
    Rejects general world knowledge, coding, sports, entertainment, politics, recipes, weather, etc.
    """
    sample = (text or "").strip().lower()
    if not sample:
        return True

    # Explicit out-of-domain topics (weather, movies, cricket, recipes, coding, politics, general trivia)
    out_of_scope_pattern = (
        r"\b(weather|cricket|ipl|football|movie|film|actor|actress|song|music|joke|poem|shayari|story|"
        r"recipe|biryani|paneer|cooking|food|president|prime\s+minister|modi|rahul\s+gandhi|election|politics|"
        r"capital\s+of|who\s+won|world\s+cup|astrology|horoscope|bitcoin|crypto|ethereum|python\s+code|"
        r"javascript\s+code|write\s+a\s+program|fibonacci|palindrome|leetcode|girlfriend|boyfriend|love|"
        r"doctor|medicine|headache|fever|train\s+ticket|flight\s+ticket|hotel\s+booking)\b|"
        r"(?:मौसम|क्रिकेट|फिल्म|गाना|कविता|शायरी|रेसिपी|खाना|प्रधानमंत्री|राजधानी|चुनाव|कोडिंग|बीमारी|दवा)"
    )
    if re.search(out_of_scope_pattern, sample, re.IGNORECASE):
        return False

    # Allowed CtrlBooks / Tally / Accounting / GST / Support / Keyboard / Troubleshooting keywords
    in_scope_pattern = (
        r"\b(ctrlbooks|ctrl\s*books|patwatoli|tally|prime|erp|connector|agent|port|sync|synchronization|"
        r"xml|odbc|heartbeat|online|offline|status|error|log|queue|pending|connect|disconnect|"
        r"voucher|vouchers|vouchcer|vauchar|vochar|vaucher|vouchr|invoice|invoices|invois|invoce|bill|billing|bills|bil|"
        r"receipt|sales|purchase|payment|contra|journal|credit\s+note|debit\s+note|"
        r"ledger|ledgers|party|parties|customer|vendor|supplier|balance|outstanding|receivable|payable|amount|"
        r"rupees|rs|inr|hazar|hazaar|lakh|crore|entry|entries|post|account|accounting|bank|cash|stock|item|"
        r"inventory|report|profit|loss|balance\s+sheet|trial\s+balance|daybook|gst|gstr|gstr1|gstr-1|gstr3b|"
        r"gstr-3b|gstr2a|gstr2b|einvoice|e-invoice|eway|e-way|irn|hsn|sac|cgst|sgst|igst|cess|tds|tcs|tax|"
        r"slab|return|filing|reconciliation|gstin|pan|ticket|support|issue|problem|bug|complaint|escalate|"
        r"sla|team|engineer|fix|solve|working|mismatch|company|dashboard|portal|widget|login|user|"
        r"dikhao|dekho|dekhna|show|get|view|fetch|list|display|banao|bna|create|generate|daal|karo|make|"
        r"trader|traders|enterprise|superfoods|"
        r"f[1-9]|f1[0-2]|fn|alt|ctrl|shortcut|shortcuts|configuration|configure|feature|features|"
        r"kaam|kam|chal|chalta|karein|karna|kaise|kahan|kyun|kyu|nahi|help|madad|troubleshoot|"
        r"hi|hello|hey|namaste|namaskar|good\s+morning|good\s+afternoon|good\s+evening|thanks|thank\s+you|"
        r"shukriya|dhanyawad|who\s+are\s+you|kaun\s+ho|kisne\s+banaya|what\s+can\s+you\s+do)\b|"
        r"(?:₹|टैली|सिंक|वाउचर|इनवॉइस|बिल|रसीद|लेजर|पार्टी|बकाया|खाता|हिसाब|पेमेंट|बिक्री|खरीद|"
        r"दिखाओ|देखो|दिखाना|जीएसटी|टैक्स|रिटर्न|टिकट|शिकायत|समस्या|एरर|नमस्ते|मदद|कंपनी|पोर्ट|टेली|વાઉચર|ટેલી|જીએસટી|ટિકિટ)"
    )
    if re.search(in_scope_pattern, sample, re.IGNORECASE):
        return True

    # Multi-turn Context Continuity: If this is an ongoing conversation (user has already exchanged messages),
    # any follow-up, clarification, or troubleshooting counter-question that is not explicitly out-of-scope
    # must be routed to the AI naturally so the LLM can use full dialogue context.
    if len(messages) >= 2:
        return True

    return False


def _build_domain_refusal_reply(lang_code: str, caller_name: str, active_company: str) -> str:
    """Generates a natural, user-specific refusal message strictly in the user's detected language when asked out-of-scope questions."""
    is_generic = (caller_name or "").strip().lower() in ("authorized user", "user", "guest", "customer", "")
    first_name = caller_name.strip().split()[0] if not is_generic else ""

    if lang_code == "en-IN":
        greet = f"Hey **{first_name}**!" if first_name else "Hello!"
        return (
            f"{greet} I am your **CtrlBooks AI Assistant** (Accounting & Tally Sub-Assistant of **PatwatoliAI**).\n\n"
            f"I specialize exclusively in **CtrlBooks** workflows — like **Tally Prime Live Sync**, creating **Sales & Receipt Vouchers**, checking **Party Ledgers**, **GST Compliance (GSTR-1 / GSTR-3B / e-Invoice)**, and raising **Support Tickets**.\n\n"
            f"Tell me what issue or task you need help with in **CtrlBooks**, and I will sort it out right away!"
        )
    if lang_code == "hi-IN":
        greet = f"नमस्ते **{first_name} जी**!" if first_name else "नमस्ते!"
        return (
            f"{greet} मैं आपका **CtrlBooks AI Assistant** (**PatwatoliAI** का अकाउंटिंग और टैली सब-असिस्टेंट) हूँ।\n\n"
            f"मैं विशेष रूप से **CtrlBooks** के कार्यों — जैसे **Tally Prime सिंक**, **सेल्स और रसीद वाउचर**, **पार्टी लेजर**, **GST कम्प्लायंस (GSTR-1 / GSTR-3B / e-Invoice)** और **सपोर्ट टिकट** में आपकी मदद के लिए बनाया गया हूँ।\n\n"
            f"कृपया बताएं आपको **CtrlBooks** में किस चीज़ में मदद चाहिए?"
        )
    if lang_code == "gu-IN":
        greet = f"નમસ્તે **{first_name}**!" if first_name else "નમસ્તે!"
        return (
            f"{greet} હું તમારો **CtrlBooks AI Assistant** (**PatwatoliAI** નો સબ-આસિસ્ટન્ટ) છું.\n\n"
            f"હું માત્ર **CtrlBooks** ના કાર્યો — જેમ કે **Tally Prime Sync**, **Sales & Receipt Vouchers**, **Ledgers**, **GST** અને **Support Tickets** માં જ મદદ કરી શકું છું.\n\n"
            f"કૃપા કરીને **CtrlBooks** સંબંધિત તમારી સમસ્યા જણાવો!"
        )
    if lang_code == "mr-IN":
        greet = f"नमस्कार **{first_name}**!" if first_name else "नमस्कार!"
        return (
            f"{greet} मी तुमचा **CtrlBooks AI Assistant** (**PatwatoliAI** चा सब-असिस्टंट) आहे.\n\n"
            f"मी फक्त **CtrlBooks** च्या कामांशी संबंधित — जसे की **Tally Prime Sync**, **Vouchers**, **Ledgers**, **GST** आणि **Support Tickets** बाबतच मदत करू शकतो.\n\n"
            f"कृपया तुम्हाला **CtrlBooks** संदर्भात जी काही समस्या असेल ती सांगा!"
        )
    # Default: Roman Hinglish
    greet = f"Namaste **{first_name} bhai**!" if first_name else "Namaste bhai!"
    return (
        f"{greet} Main aapka **CtrlBooks AI Assistant** (**PatwatoliAI** ka Accounting & Tally Sub-Assistant) hoon.\n\n"
        f"Main khaas taur par **CtrlBooks** ke kaamo — jaise **Tally Prime Live Sync**, **Sales & Receipt Vouchers**, **Party Ledgers**, **GST Compliance (GSTR-1 / 3B)**, aur **Support Tickets** mein aapki madad ke liye bana hoon.\n\n"
        f"Aapko **CtrlBooks** ya **Tally** ke regarding jo bhi issue ya kaam hai, bas bata dijiye — abhi solve karte hain!"
    )


class AIGateway:
    """Multi-provider Enterprise Multilingual AI Gateway with Auto-LID, slot-filling, and live Tally tool execution."""

    def __init__(self):
        self.base_url = settings.AI_GATEWAY_BASE_URL.rstrip("/")
        self.api_key = settings.AI_API_KEY
        self.default_model = settings.AI_DEFAULT_MODEL
        self.fallback_model = settings.AI_FALLBACK_MODEL

    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        ctx: TenantContext,
        company_name: Optional[str] = None,
        knowledge_context: Optional[List[Dict[str, Any]]] = None,
        db: Optional[Any] = None,
        conversation_id: Optional[str] = None,
        user_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Orchestrates automatic language detection, live Tally tool execution, ticket creation, and localized response generation."""
        last_user_message = messages[-1]["content"].strip() if messages else ""
        detected = detect_language_and_script(last_user_message)
        lang_code = detected["code"]
        lang_name = detected["name"]
        recommended_voice = detected["voice"]

        normalized_msg = normalize_indian_numerals(last_user_message)
        last_msg_lower = normalized_msg.lower()
        raw_company = (company_name or "CtrlBooks").strip()
        active_company = re.sub(r"\bCtrlBooks\s+(?:Pvt\.?\s*Ltd\.?|Demo\s+Ltd\.?)\b", "CtrlBooks", raw_company, flags=re.IGNORECASE)
        today_date = datetime.date.today().isoformat()
        caller = _resolve_caller_identity(user_meta, ctx, active_company)
        sample_party = _discover_sample_party(active_company)

        executed_tools = []
        tool_results_text = ""

        # 0. Strict CtrlBooks Domain Scope Guardrail: Reject out-of-scope questions immediately in the user's exact language
        if not _is_ctrlbooks_domain_query(last_user_message, messages):
            refusal_reply = _build_domain_refusal_reply(lang_code, caller["name"], active_company)
            return {
                "content": refusal_reply,
                "tool_calls": [],
                "usage": _estimate_token_usage(messages, refusal_reply),
                "model": "patwatoliai-ctrlbooks-subassistant-v1",
                "detected_language": lang_name,
                "language_code": lang_code,
                "recommended_voice": recommended_voice,
            }

        # 1. Dynamic Knowledge Context String
        knowledge_prompt_text = ""
        if knowledge_context:
            knowledge_prompt_text = "\n[Verified CtrlBooks Documentation]:\n" + "\n".join(
                f"• {chunk.get('title', 'Guide')}: {chunk.get('content', '')}" for chunk in knowledge_context
            )

        # 1.5 Check Support Ticket Status / Tracking Intent
        ticket_id_match = re.search(r"CB-\d{8}-[A-Za-z0-9]{4}", last_user_message, re.IGNORECASE)
        is_check_ticket_intent = bool(
            ticket_id_match
            or re.search(
                r"\b(status|track|check|kya hua|update|solve hua|progress|state|closed|resolved|स्टेटस|चेक|अपडेट|सॉल्व)\b.*?\b(ticket|tickets|issue|complaint|शिकायत|टिकट)\b|\b(ticket|tickets|issue|complaint|शिकायत|टिकट)\b.*?\b(status|track|check|kya hua|update|solve hua|progress|state|closed|resolved|स्टेटस|चेक|अपडेट|सॉल्व)\b|\b(mera ticket|my ticket|pichla ticket|ticket ka kya hua)\b",
                last_msg_lower,
                re.IGNORECASE,
            )
        )

        slot_missing_reply = None

        if is_check_ticket_intent and db is not None:
            from app.models.ticket import SupportTicket
            from sqlalchemy import select, desc
            from sqlalchemy.orm import selectinload

            clean_tid = ticket_id_match.group(0).upper() if ticket_id_match else None
            stmt = select(SupportTicket).options(selectinload(SupportTicket.messages)).order_by(desc(SupportTicket.created_at))
            if clean_tid:
                stmt = stmt.where(SupportTicket.id.ilike(f"%{clean_tid}%"))
            else:
                stmt = stmt.limit(5)

            res = await db.execute(stmt)
            matched_tickets = res.scalars().all()

            if matched_tickets:
                matched = matched_tickets[0]
                agent_msgs = [m for m in matched.messages if m.sender_type in ("AGENT", "SUPPORT") and not m.is_internal]
                latest_reply = agent_msgs[-1].message if agent_msgs else None

                ticket_info = {
                    "ticket_id": matched.id,
                    "subject": matched.subject,
                    "status": matched.status,
                    "priority": matched.priority,
                    "description": matched.description,
                    "created_at": matched.created_at.isoformat(),
                    "updated_at": matched.updated_at.isoformat() if matched.updated_at else None,
                    "resolved_at": matched.resolved_at.isoformat() if matched.resolved_at else None,
                    "engineer_reply": latest_reply,
                    "department": (matched.ai_summary or {}).get("department", "L2 Connector Engineering"),
                    "sla_tier": (matched.ai_summary or {}).get("sla_tier", "P3 - Standard"),
                    "resolution_sla": (matched.ai_summary or {}).get("resolution_sla", "Within 4 Hours"),
                    "diagnostics": (matched.ai_summary or {}).get("diagnostics", {}),
                    "company": (matched.ai_summary or {}).get("company", active_company),
                }
                executed_tools.append({"tool": "check_support_ticket_status", "result": ticket_info})
                tool_results_text += f"\n[Ticket Status Lookup]: ID={matched.id}, Status={matched.status}, Latest Reply='{latest_reply or 'No engineer notes yet'}'"
            else:
                slot_missing_reply = (
                    f"Mujhe **{active_company}** ke liye koi matching support ticket nahi mila"
                    + (f" (Ticket #{clean_tid})" if clean_tid else "")
                    + ".\n\nAgar aapka koi issue pending hai ya naya ticket raise karna hai, toh boliye main abhi naya ticket bana deta hoon!"
                )

        # 2. Check Support Ticket / Escalation Intent (Multilingual Corporate Intake)
        is_ticket_intent = (not is_check_ticket_intent) and bool(
            re.search(
                r"\b(ticket|support\s+ticket|complaint|escalate|issue\s+raise|raise\s+a?\s*ticket|log\s+a?\s*ticket|bana do ticket|create ticket)\b|(?:टिकट|शिकायत|सपोर्ट\s*टिकट|ટિકિટ)",
                last_msg_lower,
                re.IGNORECASE,
            )
        )

        if is_ticket_intent and db is not None:
            from app.modules.tickets.service import TicketService
            from app.modules.tickets.classifier import (
                extract_issue_context_from_conversation,
                classify_corporate_ticket,
            )

            live_tally = await connector_client.get_connection_status(
                company_name=active_company,
                user_email=caller["email"],
                preferred_port=caller["tally_port"],
            )
            active_p = live_tally.get("tally_port") or "Auto-Detect"
            has_context, full_issue_desc = extract_issue_context_from_conversation(last_user_message, messages)

            if not has_context:
                if lang_code == "en-IN":
                    slot_missing_reply = (
                        f"I am ready to generate an official **CtrlBooks Enterprise Support Ticket** for **{active_company}**!\n\n"
                        "Please briefly describe the issue you are facing so I can route it to the right engineering team with live Tally diagnostics:\n"
                        f"• **1. Tally Sync & Port {active_p}**: *'Create a ticket for Tally Port {active_p} sync error'*\n"
                        "• **2. GST & e-Invoice**: *'Raise a ticket for GSTR-1 tax mismatch'*\n"
                        "• **3. Voucher & Ledger Queue**: *'Create a ticket for pending sales voucher not posting'*"
                    )
                elif lang_code == "hi-IN":
                    slot_missing_reply = (
                        f"मैं **{active_company}** के लिए आधिकारिक **CtrlBooks सपोर्ट टिकट** बनाने के लिए तैयार हूँ!\n\n"
                        "कृपया अपनी समस्या का संक्षिप्त विवरण बताएं ताकि सही इंजीनियरिंग टीम को लाइव Tally डायग्नोस्टिक्स के साथ असाइन किया जा सके:\n"
                        f"• *'टैली पोर्ट {active_p} सिंक एरर के लिए टिकट बना दो'*\n"
                        "• *'GST रिटर्न मिसमैच के लिए टिकट दर्ज करो'*"
                    )
                else:
                    slot_missing_reply = (
                        f"Main **{active_company}** ke liye official **CtrlBooks Corporate Support Ticket** generate karne ke liye ready hoon!\n\n"
                        "Kripya apna **Issue / Problem** batayein taaki main live Tally diagnostics ke sath sahi engineering team ko assign kar sakun:\n"
                        f"• *'Tally Port {active_p} sync error ke liye urgent ticket bana do'*\n"
                        "• *'Sales voucher ledger mismatch ka support ticket raise karo'*\n"
                        "• *'GST return filing issue ke liye ticket bana do'*"
                    )
            else:
                queued_cmds = command_queue_service.list_queued_commands()
                company_queue_count = len([c for c in queued_cmds if c.get("company") == active_company])

                spec = classify_corporate_ticket(
                    issue_text=full_issue_desc,
                    company_name=active_company,
                    detected_language=lang_name,
                    tally_status=live_tally,
                    queued_vouchers_count=company_queue_count,
                    caller_name=caller["name"],
                    caller_email=caller["email"],
                    caller_phone=caller["phone"],
                )

                ticket_svc = TicketService(db)
                db_user_id = str(getattr(ctx, "user_id", None) or "1e336198-e0dc-4ede-bf84-20165e022c67")
                db_tenant_id = str(getattr(ctx, "tenant_id", None) or "3733647b-374b-404a-8dc8-382b7de1abd3")
                try:
                    created_ticket = await ticket_svc.create_ticket(
                        tenant_id=db_tenant_id,
                        user_id=db_user_id,
                        subject=spec["subject"],
                        description=full_issue_desc,
                        priority=spec["priority"],
                        conversation_id=conversation_id,
                        ai_summary=spec["ai_summary"],
                    )
                except Exception:
                    await db.rollback()
                    created_ticket = await ticket_svc.create_ticket(
                        tenant_id="3733647b-374b-404a-8dc8-382b7de1abd3",
                        user_id="1e336198-e0dc-4ede-bf84-20165e022c67",
                        subject=spec["subject"],
                        description=full_issue_desc,
                        priority=spec["priority"],
                        conversation_id=None,
                        ai_summary=spec["ai_summary"],
                    )
                t_data = {
                    "ticket_id": created_ticket.id,
                    "subject": created_ticket.subject,
                    "description": full_issue_desc,
                    "priority": created_ticket.priority,
                    "status": created_ticket.status,
                    "company": active_company,
                    "user_id": f"{caller['name']} ({caller['email']} | {caller['phone']})",
                    "customer_name": caller["name"],
                    "customer_email": caller["email"],
                    "customer_phone": caller["phone"],
                    "category_code": spec["category_code"],
                    "category_name": spec["category_name"],
                    "department": spec["department"],
                    "sla_tier": spec["sla_tier"],
                    "response_sla": spec["response_sla"],
                    "resolution_sla": spec["resolution_sla"],
                    "assigned_team": spec["assigned_team"],
                    "diagnostics": spec["ai_summary"]["diagnostics"],
                    "created_at": created_ticket.created_at.isoformat(),
                }
                executed_tools.append({"tool": "create_support_ticket", "result": t_data})
                tool_results_text += f"\n[Corporate Support Ticket Created]: ID={created_ticket.id}, Dept={spec['department']}, SLA={spec['resolution_sla']}"

        # 3. Check Live Connection Status Intent (Multilingual keywords)
        if any(w in last_msg_lower for w in ["connect", "online", "status", "chal raha", "offline", "स्टेटस", "कनेक्ट", "ऑनलाइन", "સ્ટેટસ"]):
            status_data = await execute_tool(
                "get_my_connection_status",
                {
                    "company_name": active_company,
                    "user_email": caller["email"],
                    "tally_port": caller["tally_port"],
                },
                ctx,
            )
            executed_tools.append({"tool": "get_my_connection_status", "result": status_data})
            tool_results_text += f"\n[Live Status]: Tally Online={status_data.get('is_online')}, Port={status_data.get('tally_port')}, Source={status_data.get('detection_source')}, Agent Version={status_data.get('agent_version')}"

        # 4. Dynamic Voucher Intent & Slot Filling (Supports Sales Invoice & Receipt Voucher + Dynamic GST Rate/IGST)
        is_voucher_intent = (not is_ticket_intent) and bool(
            re.search(
                r"(voucher|invoice|bill|receipt|entry|इनवॉइस|बिल|वाउचर|रसीद|બિલ|इन्व्हॉइस).*?(bna|bana|create|generate|daal|karo|kaat|kat|make|new|बना|बनवा|બનાવો)|(bna|bana|create|generate|daal|karo|make|new|बना|बनवा|બનાવો).*?(voucher|invoice|bill|receipt|entry|इनवॉइस|बिल|वाउचर|रसीद|બિલ|इन्व्हॉइस)",
                last_msg_lower,
                re.IGNORECASE,
            )
        )

        extracted = extract_voucher_entities(last_user_message) if is_voucher_intent else None

        if is_voucher_intent and extracted:
            amt = extracted.get("amount")
            party = extracted.get("party")
            v_type = extracted.get("voucher_type", "Sales")
            gst_rate = extracted.get("gst_rate", 18.0)
            is_igst = extracted.get("is_igst", False)

            if not party and amt:
                if lang_code == "en-IN":
                    slot_missing_reply = (
                        f"I am ready to generate a **{v_type} Voucher** for **₹{amt:,.2f}**!\n\n"
                        f"Please provide the **Customer / Party Name** (e.g., *'{sample_party}'*)."
                    )
                elif lang_code == "hi-IN":
                    slot_missing_reply = (
                        f"मैं **₹{amt:,.2f}** का **{v_type} वाउचर** बनाने के लिए तैयार हूँ!\n\n"
                        f"कृपया **पार्टी / ग्राहक का नाम** बताएं (जैसे: *'{sample_party}'*)."
                    )
                else:
                    slot_missing_reply = (
                        f"Main **₹{amt:,.2f}** ka **{v_type} Voucher** create karne ke liye ready hoon!\n\n"
                        f"Kripya **Customer / Party Name** batayein (Jaise: *'{sample_party}'*)."
                    )
            elif not amt and party:
                if lang_code == "en-IN":
                    slot_missing_reply = (
                        f"I am ready to create a **{v_type} Voucher** for **{party}**!\n\n"
                        f"Please specify the **Voucher Amount**."
                    )
                elif lang_code == "hi-IN":
                    slot_missing_reply = (
                        f"मैं **{party}** के लिए **{v_type} वाउचर** बनाने के लिए तैयार हूँ!\n\n"
                        f"कृपया **राशि (Amount)** बताएं।"
                    )
                else:
                    slot_missing_reply = (
                        f"Main **{party}** ke liye **{v_type} Voucher** create karne ke liye ready hoon!\n\n"
                        f"Kripya **Amount** batayein."
                    )
            elif not party and not amt:
                if lang_code == "en-IN":
                    slot_missing_reply = (
                        f"To create a **{v_type} Voucher** in **{active_company}**, please specify the **Party Name** and **Amount**.\n\n"
                        f"Example: *'Create a sales invoice for {sample_party} of ₹25,000'*"
                    )
                elif lang_code == "hi-IN":
                    slot_missing_reply = (
                        f"**{active_company}** में वाउचर बनाने के लिए कृपया **पार्टी का नाम** और **राशि (Amount)** बताएं।\n\n"
                        f"उदाहरण: *'{sample_party} के लिए 25,000 का सेल्स इनवॉइस बना दो'*"
                    )
                else:
                    slot_missing_reply = (
                        f"**{active_company}** me Voucher create karne ke liye kripya **Party Name** aur **Amount** batayein.\n\n"
                        f"Format: *'{sample_party} ke liye 25,000 ka sales invoice bana do'*"
                    )
            else:
                target_comp_name = extracted.get("target_company")
                effective_company = active_company
                effective_company_id = caller.get("company_id")

                if target_comp_name:
                    comp_details = await connector_client.resolve_company_details(
                        company_name=target_comp_name,
                        token=caller.get("connector_token"),
                    )
                    if comp_details.get("company_id"):
                        effective_company = comp_details.get("company_name", target_comp_name)
                        effective_company_id = comp_details["company_id"]
                elif effective_company.lower() in ("ctrlbooks", "your company", "active company", "default", ""):
                    try:
                        comp_details = await connector_client.resolve_company_details(token=caller.get("connector_token"))
                        effective_company = comp_details.get("company_name", effective_company)
                        effective_company_id = comp_details.get("company_id", effective_company_id)
                    except Exception:
                        pass

                common_kw = {
                    "company_name": effective_company,
                    "company_id": effective_company_id,
                    "connector_token": caller.get("connector_token"),
                    "tally_port": caller.get("tally_port"),
                }

                if v_type == "Receipt":
                    voucher_data = await execute_tool(
                        "create_receipt_voucher_command",
                        {
                            **common_kw,
                            "party_ledger": party,
                            "bank_or_cash_ledger": "Bank Account",
                            "amount": amt,
                            "date": today_date,
                        },
                        ctx,
                    )
                    executed_tools.append({"tool": "create_receipt_voucher_command", "result": voucher_data})
                elif v_type == "Payment":
                    voucher_data = await execute_tool(
                        "create_payment_voucher_command",
                        {
                            **common_kw,
                            "party_ledger": party,
                            "bank_or_cash_ledger": "Bank Account",
                            "amount": amt,
                            "date": today_date,
                        },
                        ctx,
                    )
                    executed_tools.append({"tool": "create_payment_voucher_command", "result": voucher_data})
                elif v_type == "Purchase":
                    voucher_data = await execute_tool(
                        "create_purchase_invoice_command",
                        {
                            **common_kw,
                            "party_ledger": party,
                            "date": today_date,
                            "total_amount": amt,
                            "gst_rate": gst_rate,
                            "items": [{"itemName": f"Material from {party}", "quantity": 1, "rate": amt, "amount": amt}],
                        },
                        ctx,
                    )
                    executed_tools.append({"tool": "create_purchase_invoice_command", "result": voucher_data})
                elif v_type == "Credit Note":
                    voucher_data = await execute_tool(
                        "create_credit_note_command",
                        {
                            **common_kw,
                            "party_ledger": party,
                            "amount": amt,
                            "date": today_date,
                            "reason": "Sales Return",
                        },
                        ctx,
                    )
                    executed_tools.append({"tool": "create_credit_note_command", "result": voucher_data})
                elif v_type == "Debit Note":
                    voucher_data = await execute_tool(
                        "create_debit_note_command",
                        {
                            **common_kw,
                            "party_ledger": party,
                            "amount": amt,
                            "date": today_date,
                            "reason": "Purchase Return",
                        },
                        ctx,
                    )
                    executed_tools.append({"tool": "create_debit_note_command", "result": voucher_data})
                elif v_type == "Contra":
                    voucher_data = await execute_tool(
                        "create_contra_command",
                        {
                            **common_kw,
                            "from_account": "Cash",
                            "to_account": "Bank Account",
                            "amount": amt,
                            "date": today_date,
                        },
                        ctx,
                    )
                    executed_tools.append({"tool": "create_contra_command", "result": voucher_data})
                elif v_type == "Journal":
                    voucher_data = await execute_tool(
                        "create_journal_command",
                        {
                            **common_kw,
                            "amount": amt,
                            "date": today_date,
                            "narration": f"Journal entry for {party or 'General'}",
                        },
                        ctx,
                    )
                    executed_tools.append({"tool": "create_journal_command", "result": voucher_data})
                else:
                    voucher_data = await execute_tool(
                        "create_sales_invoice_command",
                        {
                            **common_kw,
                            "party_ledger": party,
                            "date": today_date,
                            "total_amount": amt,
                            "gst_rate": gst_rate,
                            "is_igst": is_igst,
                            "narration": f"AI Multilingual {v_type} Voucher ({lang_name})",
                            "items": [{"name": f"{v_type} - {party}", "itemName": f"{v_type} - {party}", "quantity": 1, "rate": amt, "units": "NOS", "amount": amt}],
                        },
                        ctx,
                    )
                    executed_tools.append({"tool": "create_sales_invoice_command", "result": voucher_data})

                tool_results_text += f"\n[Voucher Queued]: Type={v_type}, ID={voucher_data.get('voucher_number')}, Company={effective_company}, Party={party}, Amount={amt}"

        # 4a. Dynamic Sales & Financial Analytics / Summary Intent (Sales, Receipts, Orders, Credit Notes)
        # Matches queries like: "mere aaj ka sales batao", "today's sales", "aaj kitni sale hui", "is mahine ka sales", "aaj ka collection batao"
        has_specific_vnum = bool(re.search(r"(?:invoice|voucher|bill|inv)\s*(?:no\.?|num\.?|#)\s*[A-Za-z0-9\-_]+", last_user_message, re.IGNORECASE)) and not bool(re.search(r"\b(total|aaj|today|kitna|kitni|kitne|summary|report)\b", last_msg_lower))
        is_sales_analytics_intent = (not is_ticket_intent) and (not is_voucher_intent) and (not has_specific_vnum) and bool(
            re.search(
                r"\b(sales?|bikri|collection|receipts?|jama|orders?|sales\s*orders?|credit\s*notes?)\b.*?\b(batao|dikhao|summary|total|report|kitna|kitni|kitne|aaj|today|yesterday|kal|kya\s+hai|analysis|figure|status)\b|"
                r"\b(aaj|today|kal|yesterday|is\s+mahine|this\s+month|pichle\s+hafte|last\s+week|last\s+\d+\s+days?)\b.*?\b(sales?|bikri|collection|receipts?|orders?|sales\s*orders?|credit\s*notes?)\b|"
                r"\b(mere|mera|apna|apne|my|our|total)\s+(?:aaj\s+ka\s+|today(?:'s)?\s+)?(sales?|bikri|collection|receipts?|orders?|credit\s*notes?)\b|"
                r"(?:आज\s*का\s*सेल्स|आज\s*की\s*बिक्री|कुल\s*सेल्स|आज\s*का\s*कलेक्शन|सेल्स\s*रिपोर्ट)",
                last_msg_lower,
                re.IGNORECASE,
            )
        )

        if is_sales_analytics_intent:
            effective_company = active_company
            effective_company_id = caller.get("company_id")

            # Determine endpoint and module label
            if any(w in last_msg_lower for w in ["credit note", "credit notes", "creditnote", "sales return", "क्रेडिट नोट"]):
                target_module = "credit-notes"
                module_name = "Credit Note"
            elif any(w in last_msg_lower for w in ["receipt", "receipts", "collection", "jama", "payment", "रसीद"]):
                target_module = "receipts"
                module_name = "Receipt"
            elif any(w in last_msg_lower for w in ["sales order", "sales orders", "salesorder", "order", "orders", "ऑर्डर"]):
                target_module = "sales-orders"
                module_name = "Sales Order"
            else:
                target_module = "sales"
                module_name = "Sales"

            # Determine date range
            today_obj = datetime.date.today()
            today_iso = today_obj.isoformat()
            if any(w in last_msg_lower for w in ["kal", "yesterday", "pichla din"]):
                y_obj = today_obj - datetime.timedelta(days=1)
                from_date = y_obj.isoformat()
                to_date = y_obj.isoformat()
                period_label = f"Kal ({y_obj.strftime('%d %b %Y')})"
            elif any(w in last_msg_lower for w in ["is mahine", "this month", "current month"]):
                first_day = today_obj.replace(day=1).isoformat()
                from_date = first_day
                to_date = today_iso
                period_label = f"Is Mahine ({today_obj.strftime('%B %Y')})"
            elif any(w in last_msg_lower for w in ["pichle hafte", "last week", "7 din", "7 days"]):
                week_ago = (today_obj - datetime.timedelta(days=7)).isoformat()
                from_date = week_ago
                to_date = today_iso
                period_label = "Pichle 7 Din (Last 7 Days)"
            else:
                # Default to today
                from_date = today_iso
                to_date = today_iso
                period_label = f"Aaj ({today_obj.strftime('%d %b %Y')})"

            # Extract search query q if user specified a party name or voucher query
            search_q = None
            q_match = re.search(r"([A-Za-z0-9\s&.\'-]+?)\s+(?:ka|ki|ke|को|का|के)\s+(?:sales|sale|receipt|collection|order|credit)", last_user_message, re.IGNORECASE)
            if q_match:
                cand_q = q_match.group(1).strip()
                cand_q = re.sub(r"^(?:bhai|bro|please|plz|ek|naya|new|mera|mere|apna|apne|aaj|today|kal)\s+", "", cand_q, flags=re.IGNORECASE).strip()
                if len(cand_q) >= 2 and cand_q.lower() not in {"is", "company", "sales", "purchase", "bill", "invoice", "voucher", "tally", "latest", "last", "pichla", "aaj", "total"}:
                    search_q = cand_q

            # Company details resolution
            comp_details = await connector_client.resolve_company_details(
                company_name=effective_company,
                company_id=effective_company_id,
                token=caller.get("connector_token"),
            )
            effective_company = comp_details.get("company_name", effective_company)
            effective_company_id = comp_details.get("company_id", effective_company_id)

            # Query the target module
            analytics_data = await connector_client.get_company_sales_module(
                endpoint_suffix=target_module,
                company_name=effective_company,
                company_id=effective_company_id,
                q=search_q,
                from_date=from_date,
                to_date=to_date,
                page=1,
                limit=20,
                token=caller.get("connector_token"),
            )
            analytics_data["period_label"] = period_label

            executed_tools.append({"tool": "get_sales_analytics_command", "result": analytics_data})
            tot_amt = analytics_data.get("total_amount", 0.0)
            tot_cnt = analytics_data.get("total_count", 0)
            items_list = analytics_data.get("items", [])
            tool_results_text += f"\n[Sales Analytics]: Company={effective_company}, Module={module_name}, Period={period_label}, TotalAmount={tot_amt}, TotalCount={tot_cnt}"

            # Format natural language corporate response
            if tot_cnt > 0 or tot_amt > 0:
                top_items_txt = ""
                for itm in items_list[:3]:
                    top_items_txt += f"  • `{itm.get('voucher_number', 'VCH')}` — **{itm.get('party_ledger', 'Customer')}**: ₹{itm.get('amount', 0):,.2f}\n"

                if lang_code == "en-IN":
                    slot_missing_reply = (
                        f"📊 **{effective_company} — {period_label} {module_name} Report:**\n\n"
                        f"• **Total {module_name} Value:** **₹{tot_amt:,.2f}**\n"
                        f"• **Total Count:** **{tot_cnt}** {module_name.lower()}(s)\n"
                        f"• **Period Range:** {from_date} to {to_date}\n\n"
                    )
                    if top_items_txt:
                        slot_missing_reply += f"**Key Transactions:**\n{top_items_txt}\n"
                    slot_missing_reply += "The interactive financial summary card has been loaded below with instant WhatsApp sharing!"
                elif lang_code == "hi-IN":
                    slot_missing_reply = (
                        f"📊 **{effective_company} — {period_label} {module_name} रिपोर्ट:**\n\n"
                        f"• **कुल राशि (Total Amount):** **₹{tot_amt:,.2f}**\n"
                        f"• **कुल वाउचर/बिल संख्या:** **{tot_cnt}**\n"
                        f"• **तारीख सीमा:** {from_date} से {to_date}\n\n"
                    )
                    if top_items_txt:
                        slot_missing_reply += f"**प्रमुख लेनदेन:**\n{top_items_txt}\n"
                    slot_missing_reply += "नीचे लाइव समरी कार्ड लोड कर दिया गया है। आप इसे सीधे व्हाट्सएप पर भी शेयर कर सकते हैं!"
                else:
                    slot_missing_reply = (
                        f"📊 **{effective_company}** ka **{period_label}** ka **{module_name}** summary mil gaya hai:\n\n"
                        f"• **Kul Bikri / Total Amount:** **₹{tot_amt:,.2f}**\n"
                        f"• **Total Vouchers / Invoices:** **{tot_cnt}**\n"
                        f"• **Date Period:** {from_date} se {to_date}\n\n"
                    )
                    if top_items_txt:
                        slot_missing_reply += f"**Top Transactions:**\n{top_items_txt}\n"
                    slot_missing_reply += "Aapke liye interactive live summary card niche ready hai, jise aap direct WhatsApp par share kar sakte hain!"
            else:
                if lang_code == "en-IN":
                    slot_missing_reply = (
                        f"ℹ️ In **{effective_company}**, no {module_name.lower()} records were found for **{period_label}** (Total: ₹0.00).\n\n"
                        f"Would you like me to create a new {module_name.lower()} voucher in Tally Prime? (e.g. *'Create sales invoice for {sample_party} of ₹15,000'*)"
                    )
                elif lang_code == "hi-IN":
                    slot_missing_reply = (
                        f"ℹ️ **{effective_company}** में **{period_label}** के लिए कोई {module_name.lower()} रिकॉर्ड नहीं मिला (कुल: ₹0.00)।\n\n"
                        f"क्या आप नया वाउचर बनाना चाहते हैं? (जैसे: *'{sample_party} के लिए 15,000 का सेल्स इनवॉइस बना दो'*)"
                    )
                else:
                    slot_missing_reply = (
                        f"ℹ️ **{effective_company}** me **{period_label}** ke liye koi {module_name.lower()} entry nahi mili (Total: ₹0.00).\n\n"
                        f"Agar aapko naya voucher banana hai, toh boliye main abhi Tally me post kar deta hoon! (e.g. *'{sample_party} ke liye 15,000 ka sales invoice bana do'*)"
                    )

        # 4b. Dynamic View/Lookup Voucher Intent (Fetches synced invoices/vouchers from Cloud/Tally)
        is_view_voucher_intent = (not is_ticket_intent) and (not is_voucher_intent) and (not is_sales_analytics_intent) and bool(
            re.search(
                r"\b(dikhao|dikha|dekho|dekhna|show|view|display|fetch|get|list|find|search|nikalo|batao|pichla|last|latest|previous|kya\s+hai)\b.*?\b(invoice|invoices|invois|bill|bills|voucher|vouchers|receipt|receipts|sale|sales|entry|entries|वाउचर|इनवॉइस|बिल|રસીદ|બિલ)\b|"
                r"\b(invoice|invoices|invois|bill|bills|voucher|vouchers|receipt|receipts|sale|sales|entry|entries|वाउचर|इनवॉइस|बिल|રસીદ|બિલ)\b.*?\b(dikhao|dikha|dekho|dekhna|show|view|display|fetch|get|list|find|search|nikalo|batao|pichla|last|latest|previous)\b|"
                r"\b(mera|mere|apna|apne|my|our)\s+(?:sales\s+)?(invoice|invoices|invois|bill|bills|voucher|vouchers|receipt|receipts|entry|entries)\b|"
                r"(?:दिखाओ|देखो|दिखाना|બતાવો|દાખવા)",
                last_msg_lower,
                re.IGNORECASE,
            )
        )

        if is_view_voucher_intent:
            effective_company = active_company
            effective_company_id = caller.get("company_id")

            # Extract target company candidate if mentioned in the prompt
            comp_view_patterns = [
                r"^(?:in\s+)?(.*?)\s+(?:me|mein|में)\s+",
                r"(?:company\s+|कंपनी\s+)?([A-Za-z0-9\s&.\'-]+?)\s+(?:ka|ki|ke|company\s+ka|company\s+ki)\s+(?:voucher|invoice|bill|receipt)",
            ]
            for pat in comp_view_patterns:
                m_c = re.search(pat, last_user_message, re.IGNORECASE)
                if m_c:
                    c_cand = m_c.group(1).strip()
                    c_cand = re.sub(r"^(?:mere|apne|my|the|in|mujhe|is)\s+", "", c_cand, flags=re.IGNORECASE).strip()
                    if len(c_cand) >= 3 and c_cand.lower() not in {"bill", "invoice", "voucher", "karo", "tally", "ctrlbooks"}:
                        comp_details = await connector_client.resolve_company_details(
                            company_name=c_cand,
                            token=caller.get("connector_token"),
                        )
                        if comp_details.get("company_id"):
                            effective_company = comp_details.get("company_name", c_cand)
                            effective_company_id = comp_details["company_id"]
                            break

            # If effective_company is generic/default, resolve from connected companies
            if effective_company.lower() in ("ctrlbooks", "your company", "active company", "default", ""):
                try:
                    comp_details = await connector_client.resolve_company_details(token=caller.get("connector_token"))
                    effective_company = comp_details.get("company_name", effective_company)
                    effective_company_id = comp_details.get("company_id", effective_company_id)
                except Exception:
                    pass

            # Extract voucher number if specified (e.g., "invoice #2", "bill 101", "INV-12")
            v_num = None
            v_num_match = re.search(r"(?:invoice|voucher|bill|inv|no|number|#)\s*(?:no\.?|num\.?|#)?\s*([A-Za-z0-9\-_]+)", last_user_message, re.IGNORECASE)
            if v_num_match:
                cand_num = v_num_match.group(1).strip()
                if cand_num.lower() not in {"dikhao", "dekho", "view", "show", "hai", "batao", "karo", "mera", "mere", "ke", "ka", "ki", "me", "mein", "sales", "bill", "invoice", "voucher"}:
                    v_num = cand_num
            if not v_num:
                v_num_match2 = re.search(r"(\d+)\s*(?:number|no|num)?\s*(?:ka\s+)?(?:bill|invoice|voucher)", last_user_message, re.IGNORECASE)
                if v_num_match2:
                    v_num = v_num_match2.group(1).strip()

            # Extract party search query (e.g., "SuperFoods ka bill dikhao")
            party_search = None
            party_match = re.search(r"([A-Za-z0-9\s&.\'-]+?)\s+(?:ka|ki|ke|को|का|के)\s+(?:bill|invoice|voucher|इनवॉइस|बिल|वाउचर)", last_user_message, re.IGNORECASE)
            if party_match:
                cand_party = party_match.group(1).strip()
                cand_party = re.sub(r"^(?:bhai|bro|please|plz|ek|naya|new|mera|mere|apna|apne)\s+", "", cand_party, flags=re.IGNORECASE).strip()
                if len(cand_party) >= 2 and cand_party.lower() not in {"is", "company", "sales", "purchase", "bill", "invoice", "voucher", "tally", "latest", "last", "pichla"}:
                    if cand_party.lower() not in effective_company.lower() and effective_company.lower() not in cand_party.lower():
                        party_search = cand_party

            v_type_filter = "Receipt" if any(w in last_msg_lower for w in ["receipt", "रसीद"]) else "Sales"

            # Query real-time synchronized vouchers from CtrlBooks Cloud API / Tally Prime
            vouchers = await connector_client.get_company_vouchers(
                company_name=effective_company,
                company_id=effective_company_id,
                voucher_type=v_type_filter,
                voucher_number=v_num,
                search=party_search,
                limit=5,
                token=caller.get("connector_token"),
            )

            if vouchers:
                top_v = vouchers[0]
                top_amt = 0.0
                try:
                    raw_val = top_v.get("amount")
                    if isinstance(raw_val, dict):
                        raw_val = raw_val.get("$numberDecimal") or raw_val.get("value") or 0.0
                    top_amt = float(str(raw_val).replace(",", "").strip() if raw_val is not None and str(raw_val).strip() != "" else 0.0)
                except Exception:
                    top_amt = 0.0

                top_items = top_v.get("items") or []
                if not top_items:
                    top_items = [{
                        "name": f"{top_v.get('voucher_type', 'Sales')} - {top_v.get('party_ledger')}",
                        "itemName": f"{top_v.get('voucher_type', 'Sales')} - {top_v.get('party_ledger')}",
                        "quantity": 1,
                        "rate": top_amt,
                        "amount": top_amt,
                    }]

                card_data = {
                    "success": True,
                    "status": top_v.get("status", "SYNCED"),
                    "command_type": "CREATE_VOUCHER",
                    "command_hash": top_v.get("id") or "synced_voucher",
                    "command_id": top_v.get("id"),
                    "voucher_number": top_v.get("voucher_number"),
                    "company": effective_company,
                    "company_id": effective_company_id,
                    "party_name": top_v.get("party_ledger"),
                    "payload": {
                        "type": "CREATE_VOUCHER",
                        "companyName": effective_company,
                        "payload": {
                            "voucher_type": top_v.get("voucher_type", "Sales"),
                            "party_ledger": top_v.get("party_ledger"),
                            "date": top_v.get("date"),
                            "amount": top_amt,
                            "taxable_amount": top_amt,
                            "gst_total": 0.0,
                            "narration": top_v.get("narration") or f"Invoice #{top_v.get('voucher_number')}",
                            "items": top_items,
                        },
                    },
                }

                executed_tools.append({"tool": "create_sales_invoice_command", "result": card_data})
                executed_tools.append({"tool": "get_company_vouchers_command", "result": {"vouchers": vouchers, "count": len(vouchers)}})
                tool_results_text += f"\n[Vouchers Retrieved]: Company={effective_company}, Total={len(vouchers)}, TopVoucher={top_v.get('voucher_number')}, Party={top_v.get('party_ledger')}, Amount={top_amt}"

                v_num_disp = top_v.get("voucher_number", "N/A")
                party_disp = top_v.get("party_ledger", "Customer")
                amt_disp = top_amt
                date_disp = top_v.get("date") or today_date
                v_type_disp = top_v.get("voucher_type", "Sales")
                status_disp = top_v.get("status", "SYNCED")

                if lang_code == "en-IN":
                    slot_missing_reply = (
                        f"Here is the verified **{v_type_disp} Invoice** for **{party_disp}** from **{effective_company}**:\n\n"
                        f"• **Company**: {effective_company}\n"
                        f"• **Invoice Number**: `{v_num_disp}`\n"
                        f"• **Party Name**: {party_disp}\n"
                        f"• **Date**: {date_disp}\n"
                        f"• **Total Amount**: ₹{amt_disp:,.2f}\n"
                        f"• **Tally Sync Status**: `{status_disp}`\n\n"
                        f"The interactive invoice card has been loaded below with full details and instant WhatsApp sharing!"
                    )
                elif lang_code == "hi-IN":
                    slot_missing_reply = (
                        f"ये रहा **{effective_company}** में **{party_disp}** का **{v_type_disp} इनवॉइस**:\n\n"
                        f"• **कंपनी**: {effective_company}\n"
                        f"• **इनवॉइस नंबर**: `{v_num_disp}`\n"
                        f"• **पार्टी का नाम**: {party_disp}\n"
                        f"• **दिनांक**: {date_disp}\n"
                        f"• **कुल राशि**: ₹{amt_disp:,.2f}\n"
                        f"• **टैली सिंक स्टेटस**: `{status_disp}`\n\n"
                        f"नीचे डिजिटल इनवॉइस कार्ड लोड कर दिया गया है। आप इसे सीधे व्हाट्सएप पर भी शेयर कर सकते हैं!"
                    )
                else:
                    slot_missing_reply = (
                        f"Ji bhai! **{effective_company}** ka verified **{v_type_disp} Invoice** mil gaya hai:\n\n"
                        f"• **Company**: {effective_company}\n"
                        f"• **Invoice Number**: `{v_num_disp}`\n"
                        f"• **Party Name**: {party_disp}\n"
                        f"• **Date**: {date_disp}\n"
                        f"• **Total Amount**: ₹{amt_disp:,.2f}\n"
                        f"• **Tally Sync Status**: `{status_disp}`\n\n"
                        f"Aapke liye interactive digital invoice card niche ready hai, jise aap direct WhatsApp par share ya print kar sakte hain!"
                    )
            else:
                executed_tools.append({"tool": "get_company_vouchers_command", "result": {"vouchers": [], "count": 0}})
                search_detail = f" ('{party_search}' ke liye)" if party_search else ""
                if lang_code == "en-IN":
                    slot_missing_reply = (
                        f"No vouchers were found in **{effective_company}**{search_detail}.\n\n"
                        f"Would you like me to create a new invoice for this party? (e.g. *'Create sales invoice for {party_search or 'SuperFoods'} of ₹5,000'*)"
                    )
                elif lang_code == "hi-IN":
                    slot_missing_reply = (
                        f"**{effective_company}** में कोई वाउचर नहीं मिला{search_detail}।\n\n"
                        f"क्या आप नया इनवॉइस बनाना चाहते हैं? (जैसे: *'{party_search or 'SuperFoods'} के लिए 5,000 का बिल बना दो'*)"
                    )
                else:
                    slot_missing_reply = (
                        f"**{effective_company}** me abhi koi voucher nahi mila{search_detail}.\n\n"
                        f"Kya aap naya voucher create karna chahte hain? Example: *'{party_search or 'SuperFoods'} ko 5000 ka bill bana do'*"
                    )

        elif any(w in last_msg_lower for w in ["sync", "fail", "error", "problem", "nahi ho raha", "सिंक"]):
            sync_data = await execute_tool("get_my_sync_status", {"company_name": active_company}, ctx)
            error_data = await execute_tool("get_my_sync_errors", {"company_name": active_company}, ctx)
            executed_tools.append({"tool": "get_my_sync_status", "result": sync_data})
            executed_tools.append({"tool": "get_my_sync_errors", "result": error_data})
            tool_results_text += f"\n[Live Sync]: Status={sync_data.get('status')}, Last Sync={sync_data.get('last_sync_time')}, Total={sync_data.get('total_records')}, Synced={sync_data.get('synced_records')}"

        # Friendly display name for conversational addressing (avoid literal 'Authorized User' or 'Your Company')
        raw_c_name = caller.get("name", "")
        is_generic_user = "authorized" in raw_c_name.lower() or raw_c_name.lower() in ("user", "guest", "customer", "")
        first_name = raw_c_name.split()[0] if not is_generic_user else ""
        friendly_hi = f"{first_name} bhai" if first_name else "Bhai"
        friendly_en = first_name if first_name else "there"
        friendly_dev = f"{first_name} जी" if first_name else "दोस्त"
        company_display = active_company if active_company.lower() not in ("your company", "active company", "ctrlbooks") else "aapke CtrlBooks workspace"

        # 5. If remote LLM API key is configured, call remote model
        # Keep exact structured cards for newly created tickets/vouchers or missing-slot prompts, and let live LLM handle identity & conversational queries naturally
        has_action_card = bool(
            slot_missing_reply
            or any(
                t["tool"] in ("create_support_ticket", "create_sales_invoice_command", "create_receipt_voucher_command")
                for t in executed_tools
            )
        )
        if (
            not has_action_card
            and self.api_key
            and not self.api_key.startswith("placeholder")
            and not self.api_key.startswith("sk-mock")
            and "your-api-key" not in self.api_key
        ):
            try:
                import asyncio

                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                if lang_code == "en-IN":
                    lang_instruction = (
                        "STRICT LANGUAGE RULE: The user wrote in PURE ENGLISH. "
                        "You MUST reply 100% in natural, warm, conversational English ONLY. Do NOT use Hindi or Hinglish words."
                    )
                elif lang_code == "hi-IN":
                    lang_instruction = (
                        "STRICT LANGUAGE RULE: The user wrote in HINDI (Devanagari script). "
                        "You MUST reply 100% in natural, warm Hindi (Devanagari script: हिंदी) ONLY. Do NOT reply in English or Roman script."
                    )
                elif lang_code == "hinglish":
                    lang_instruction = (
                        "STRICT LANGUAGE RULE: The user wrote in ROMAN HINGLISH (Hindi written in English/Latin alphabet). "
                        f"You MUST reply 100% in natural, friendly conversational Roman Hinglish (addressing the user as '{friendly_hi}'). "
                        "Do NOT sound like a translated textbook or robotic template. Speak like a smart Indian CA / CtrlBooks colleague."
                    )
                else:
                    lang_instruction = (
                        f"STRICT LANGUAGE RULE: The user wrote in {lang_name} ({lang_code}). "
                        f"You MUST reply 100% in {lang_name} using its native script ONLY."
                    )

                system_prompt = (
                    "You are the CtrlBooks AI Assistant — a smart, friendly Accounting & Tally Prime Sub-Assistant built on PatwatoliAI.\n\n"
                    "TONE & CONVERSATION STYLE (VERY IMPORTANT):\n"
                    "- Speak like a sharp, warm, human Chartered Accountant & CtrlBooks expert sitting right next to the user.\n"
                    "- NEVER use stiff, robotic labels like 'Identity:', 'Capabilities:', 'Core Identity:', or 'Summary:'.\n"
                    "- Write naturally with a warm opening sentence followed by 2-4 clean, actionable points only when helpful.\n"
                    f"- Address the user naturally as '{friendly_hi}' (in Hinglish), '{friendly_dev}' (in Hindi), or '{friendly_en}' (in English). Never call the user 'Authorized User' or 'My Company'.\n\n"
                    "STRICT BRANDING & IDENTITY RULE:\n"
                    "- If asked who you are, who built you, or which AI model you are, naturally explain that you are the **CtrlBooks AI Assistant**, a specialized Accounting & Tally Prime **Sub-Assistant of PatwatoliAI**, built to handle Tally Prime live sync, Sales/Receipt vouchers, GST compliance, and instant Support Tickets.\n"
                    "- NEVER mention Mistral, Ministral, OpenAI, ChatGPT, or any third-party AI provider.\n\n"
                    "STRICT DOMAIN RESTRICTION RULE (CTRLBOOKS ONLY):\n"
                    "- You ONLY help with CtrlBooks, Tally Prime sync, Vouchers (Sales/Receipt/Purchase/Payment), Ledgers, GST Compliance (GSTR-1, GSTR-3B, e-Invoice, HSN/SAC), and CtrlBooks Support Tickets.\n"
                    "- If the user asks ANYTHING outside of CtrlBooks / Tally / Accounting / GST, politely decline and ask them to share their issue regarding CtrlBooks.\n\n"
                    f"{lang_instruction}\n\n"
                    f"Today's date: {today_date} | Active Tally Port: {caller.get('tally_port') or 'Auto-Detect'}\n"
                    f"Live Tally & Connector Telemetry:\n{tool_results_text}\n"
                    f"{knowledge_prompt_text}"
                )
                clean_messages = [
                    {"role": m.get("role", "user"), "content": str(m.get("content", ""))}
                    for m in messages[-8:]
                ]
                async with httpx.AsyncClient(timeout=18.0) as client:
                    for attempt, model_to_use in enumerate([self.default_model, self.fallback_model]):
                        payload = {
                            "model": model_to_use,
                            "messages": [{"role": "system", "content": system_prompt}] + clean_messages,
                            "temperature": 0.3,
                            "max_tokens": 700,
                        }
                        res = await client.post(
                            f"{self.base_url.rstrip('/')}/chat/completions",
                            headers=headers,
                            json=payload,
                        )
                        if res.status_code == 200:
                            data = res.json()
                            if "choices" in data and data["choices"]:
                                content = (
                                    data["choices"][0].get("message", {}).get("content")
                                    or data["choices"][0].get("text", "")
                                )
                            else:
                                content = data.get("response") or data.get("content") or data.get("message", "")
                            if content:
                                clean_content = _sanitize_brand_identity(content.strip())
                                usage = data.get("usage") or _estimate_token_usage(messages, clean_content)
                                return {
                                    "content": clean_content,
                                    "tool_calls": executed_tools,
                                    "usage": usage,
                                    "model": "patwatoliai-ctrlbooks-subassistant-v1",
                                    "detected_language": lang_name,
                                    "language_code": lang_code,
                                    "recommended_voice": recommended_voice,
                                }
                        elif res.status_code == 429 and attempt == 0:
                            await asyncio.sleep(1.2)
                            continue
                        else:
                            logger.warning(
                                f"Remote LLM gateway ({self.base_url}/chat/completions, model={model_to_use}) "
                                f"returned HTTP {res.status_code}: {res.text[:200]}"
                            )
                            break
            except Exception as e:
                logger.error(f"Error calling remote LLM gateway: {e}. Falling back to resilient multilingual engine.")

        # 6. Dynamic Grounded Multilingual Response Synthesis (100% Data-Driven from Tool & RAG Outputs)
        if slot_missing_reply:
            reply = slot_missing_reply
        else:
            analytics_tool = next((t for t in executed_tools if t["tool"] == "get_sales_analytics_command"), None)
            status_tool = next((t for t in executed_tools if t["tool"] == "check_support_ticket_status"), None)
            ticket_tool = next((t for t in executed_tools if t["tool"] == "create_support_ticket"), None)
            voucher_tool = next(
                (t for t in executed_tools if t["tool"] in ("create_sales_invoice_command", "create_receipt_voucher_command")),
                None,
            )
            if analytics_tool:
                a_res = analytics_tool["result"]
                tot_amt = a_res.get("total_amount", 0.0)
                tot_cnt = a_res.get("total_count", 0)
                mod_name = a_res.get("module_label", "Sales")
                period = a_res.get("period_label", "Aaj")
                reply = (
                    f"📊 **{a_res.get('company_name', active_company)} — {period} {mod_name} Report:**\n\n"
                    f"• **Total {mod_name} Value:** **₹{tot_amt:,.2f}**\n"
                    f"• **Total Count:** **{tot_cnt}** {mod_name.lower()}(s)\n"
                    f"• **Period Range:** {a_res.get('from_date')} to {a_res.get('to_date')}\n\n"
                    f"Aapke liye interactive live summary card niche load kar diya gaya hai!"
                )
            elif status_tool:
                s_res = status_tool["result"]
                s_id = s_res.get("ticket_id")
                s_subj = s_res.get("subject", "Support Request")
                s_status = s_res.get("status", "OPEN")
                s_reply = s_res.get("engineer_reply")
                s_sla = s_res.get("resolution_sla", "Within 4 Hours")

                if s_status == "RESOLVED":
                    reply = (
                        f"🎉 Aapka support ticket **`#{s_id}`** successfully **RESOLVED** ho chuka hai!\n\n"
                        f"• **Subject:** {s_subj}\n"
                        f"• **Live Status:** ✅ RESOLVED\n"
                    )
                    if s_reply:
                        reply += f"• 💬 **Support Engineer ka Samadhaan/Reply:**\n  *\"{s_reply}\"*\n\n"
                    reply += "Aap neeche card se **Download PDF** par click karke updated PDF receipt bhi le sakte hain."
                elif s_status == "IN_PROGRESS":
                    reply = (
                        f"⏳ Aapka ticket **`#{s_id}`** abhi **IN PROGRESS** hai!\n\n"
                        f"• **Subject:** {s_subj}\n"
                        f"• **Live Status:** 🟡 IN PROGRESS\n"
                        f"• **Target Resolution SLA:** {s_sla}\n"
                    )
                    if s_reply:
                        reply += f"• 💬 **Latest Engineer Update:** *\"{s_reply}\"*\n\n"
                    reply += "Humare L2 engineers ispar kaam kar rahe hain. Jald hi update milega!"
                elif s_status == "CLOSED":
                    reply = (
                        f"Aapka ticket **`#{s_id}`** abhi **CLOSED** status par hai.\n\n"
                        f"• **Subject:** {s_subj}\n"
                    )
                    if s_reply:
                        reply += f"• 💬 **Resolution Summary:** *\"{s_reply}\"*\n\n"
                else:
                    reply = (
                        f"Aapka ticket **`#{s_id}`** queue me **OPEN** hai aur engineer desk ko assign kiya ja chuka hai.\n\n"
                        f"• **Subject:** {s_subj}\n"
                        f"• **Live Status:** 📩 OPEN\n"
                        f"• **Target Resolution:** {s_sla}"
                    )
            elif ticket_tool:
                t_res = ticket_tool["result"]
                t_id = t_res.get("ticket_id")
                t_subj = t_res.get("subject", "Support Request")
                t_dept = t_res.get("department", "L2 Connector Engineering")
                t_sla_tier = t_res.get("sla_tier", "P2 - High")
                t_resp_sla = t_res.get("response_sla", "1 Hour")
                t_res_sla = t_res.get("resolution_sla", "4 Hours")
                t_diag = t_res.get("diagnostics", {})
                t_port = t_diag.get("tally_port", "Auto")

                raw_cust = str(t_res.get("customer_name") or "")
                is_gen_cust = "authorized" in raw_cust.lower() or raw_cust.lower() in ("user", "guest", "customer", "")
                cust_en = f"for **{raw_cust}**" if not is_gen_cust else "for your account"
                cust_hi = f"**{raw_cust}** के लिए" if not is_gen_cust else "आपके लिए"
                cust_hing = f"**{raw_cust}** ke liye" if not is_gen_cust else "aapke liye"

                if lang_code == "en-IN":
                    reply = (
                        f"Official **CtrlBooks Service Request (`#{t_id}`)** has been registered {cust_en} and routed to **{t_dept}**!\n\n"
                        f"• **Ticket Reference**: `{t_id}`\n"
                        f"• **Subject**: {t_subj}\n"
                        f"• **Assigned Desk**: {t_dept} ({t_res.get('assigned_team')})\n"
                        f"• **SLA Priority Tier**: `{t_sla_tier}` (Response: **{t_resp_sla}** | Target Resolution: **{t_res_sla}**)\n"
                        f"• **Auto-Attached Diagnostics**: Tally Port `{t_port}` (`{t_diag.get('tally_connector', 'ONLINE')}`), Queue Items: `{t_diag.get('pending_queue_items', 0)}`"
                    )
                elif lang_code == "hi-IN":
                    reply = (
                        f"{cust_hi} आधिकारिक **CtrlBooks सर्विस टिकट (`#{t_id}`)** दर्ज कर लिया गया है और **{t_dept}** को सौंप दिया गया है!\n\n"
                        f"• **टिकट नंबर**: `{t_id}`\n"
                        f"• **विषय**: {t_subj}\n"
                        f"• **विभाग (Department)**: {t_dept}\n"
                        f"• **SLA प्राथमिकता**: `{t_sla_tier}` (प्रतिक्रिया: **{t_resp_sla}** | समाधान समय: **{t_res_sla}**)\n"
                        f"• **ऑटो-अटैच्ड डायग्नोस्टिक्स**: Tally Port `{t_port}` (`{t_diag.get('tally_connector', 'ONLINE')}`)"
                    )
                else:
                    reply = (
                        f"Ji bilkul! Maine {cust_hing} official **CtrlBooks Corporate Service Ticket (`#{t_id}`)** generate karke **{t_dept}** ko assign kar diya hai:\n\n"
                        f"• **Ticket Reference**: `{t_id}`\n"
                        f"• **Subject**: {t_subj}\n"
                        f"• **Assigned Department**: {t_dept} ({t_res.get('assigned_team')})\n"
                        f"• **SLA Priority Tier**: `{t_sla_tier}` (First Response: **{t_resp_sla}** | Resolution Target: **{t_res_sla}**)\n"
                        f"• **Auto-Attached Diagnostics**: Tally Port `{t_port}` (`{t_diag.get('tally_connector', 'ONLINE')}`), Pending Queue: `{t_diag.get('pending_queue_items', 0)}` vouchers\n\n"
                        f"Support team ko aapka live diagnostic snapshot mil chuka hai!"
                    )
            elif voucher_tool:
                v_res = voucher_tool["result"]
                v_payload = v_res.get("payload", {}).get("payload", {})
                v_type_label = v_payload.get("voucher_type", "Sales")
                party = v_payload.get("party_ledger", "Customer")
                total_incl_gst = float(v_payload.get("amount", 0.0))
                subtotal = float(v_payload.get("taxable_amount", total_incl_gst))
                gst_total = float(v_payload.get("gst_total", round(total_incl_gst - subtotal, 2)))
                tax_label = v_payload.get("tax_label", "9% CGST + 9% SGST")
                v_no = v_res.get("voucher_number")

                live_status = await connector_client.get_connection_status(
                    company_name=active_company,
                    user_email=caller["email"],
                    preferred_port=caller["tally_port"],
                )
                live_port = live_status.get("tally_port", "Auto")

                if lang_code == "en-IN":
                    reply = (
                        f"Done! I have created the **{v_type_label} Voucher** for **{party}** and queued it in the **CtrlBooks 2-Way Sync Queue**:\n\n"
                        f"• **Company**: {active_company}\n"
                        f"• **Voucher Number**: `{v_no}`\n"
                        f"• **Party Name**: {party}\n"
                        f"• **Date**: {today_date}\n"
                        f"• **Taxable Subtotal**: ₹{subtotal:,.2f}\n"
                        f"• **GST ({tax_label})**: ₹{gst_total:,.2f}\n"
                        f"• **Total Voucher Value**: ₹{total_incl_gst:,.2f}\n"
                        f"• **Status**: `{v_res.get('status', 'QUEUED')}` for Tally Prime Port {live_port}."
                    )
                elif lang_code == "hi-IN":
                    reply = (
                        f"जी बिल्कुल! मैंने **{party}** के लिए **{v_type_label} वाउचर** सफलतापूर्वक बनाकर **CtrlBooks 2-Way Queue** में जोड़ दिया है:\n\n"
                        f"• **कंपनी**: {active_company}\n"
                        f"• **वाउचर नंबर**: `{v_no}`\n"
                        f"• **पार्टी का नाम**: {party}\n"
                        f"• **दिनांक**: {today_date}\n"
                        f"• **टैक्सेबल राशि**: ₹{subtotal:,.2f}\n"
                        f"• **GST ({tax_label})**: ₹{gst_total:,.2f}\n"
                        f"• **कुल वाउचर राशि**: ₹{total_incl_gst:,.2f}\n\n"
                        f"यह वाउचर स्वचालित रूप से आपके Tally Prime (Port {live_port}) के साथ सिंक हो जाएगा!"
                    )
                elif lang_code == "gu-IN":
                    reply = (
                        f"જી ચોક્કસ! મેં **{party}** માટે **{v_type_label} વાઉચર** બનાવીને **CtrlBooks 2-Way Queue** માં મૂકી દીધું છે:\n\n"
                        f"• **કંપની**: {active_company}\n"
                        f"• **વાઉચર નંબર**: `{v_no}`\n"
                        f"• **પાર્ટીનું નામ**: {party}\n"
                        f"• **GST ({tax_label})**: ₹{gst_total:,.2f}\n"
                        f"• **કુલ રકમ**: ₹{total_incl_gst:,.2f}\n\n"
                        f"આ વાઉચર Tally Prime પોર્ટ {live_port} સાથે આપમેળે સિંક થઈ જશે!"
                    )
                elif lang_code == "mr-IN":
                    reply = (
                        f"नक्कीच! मी **{party}** साठी **{v_type_label} व्हाउचर** तयार करून **CtrlBooks 2-Way Queue** मध्ये जोडले आहे:\n\n"
                        f"• **कंपनी**: {active_company}\n"
                        f"• **व्हाउचर नंबर**: `{v_no}`\n"
                        f"• **पार्टीचे नाव**: {party}\n"
                        f"• **GST ({tax_label})**: ₹{gst_total:,.2f}\n"
                        f"• **एकूण रक्कम**: ₹{total_incl_gst:,.2f}\n\n"
                        f"हे व्हाउचर तुमच्या Tally Prime (Port {live_port}) सोबत आपोआप सिंक होईल!"
                    )
                else:
                    reply = (
                        f"Ji bilkul! Maine **{party}** ke liye **{v_type_label} Voucher** successfully create karke **CtrlBooks 2-Way Queue** me daal diya hai:\n\n"
                        f"• **Company**: {active_company}\n"
                        f"• **Voucher Type**: {v_type_label} Voucher\n"
                        f"• **Voucher Number**: `{v_no}`\n"
                        f"• **Party Name**: {party}\n"
                        f"• **Date**: {today_date}\n"
                        f"• **Taxable Subtotal**: ₹{subtotal:,.2f}\n"
                        f"• **GST ({tax_label})**: ₹{gst_total:,.2f}\n"
                        f"• **Total Value**: ₹{total_incl_gst:,.2f}\n"
                        f"• **Status**: `{v_res.get('status', 'QUEUED')}` (Hash: `{v_res.get('command_hash', '')[:12]}...`)\n\n"
                        f"Ye voucher automatically aapke Tally Prime (Port {live_port}) ke sath sync ho jayega!"
                    )

            elif any(w in last_msg_lower for w in ["connect", "online", "status", "स्टेटस", "कनेक्ट", "ऑनलाइन", "સ્ટેટસ"]):
                s = await connector_client.get_connection_status(
                    company_name=active_company,
                    user_email=caller["email"],
                    preferred_port=caller["tally_port"],
                )
                port = s.get("tally_port", "Auto")
                source = s.get("detection_source", "DYNAMIC_SCAN")
                online_str = "Online" if s.get("is_online", True) else "Offline"

                if lang_code == "en-IN":
                    reply = (
                        f"Your Tally Prime Connector for **{active_company}** is currently **{online_str.upper()}**!\n\n"
                        f"• **Active Port**: {port} (`{source}`)\n"
                        f"• **Company**: {active_company}\n"
                        f"• **Agent Version**: {s.get('agent_version', '1.0.1')}\n\n"
                        f"Would you like to check ledger synchronization or generate a new voucher?"
                    )
                elif lang_code == "hi-IN":
                    reply = (
                        f"**{active_company}** के लिए आपका Tally Prime कनेक्टर अभी **{online_str.upper()}** है!\n\n"
                        f"• **सक्रिय पोर्ट**: {port} (`{source}`)\n"
                        f"• **कंपनी**: {active_company}\n"
                        f"• **एजेंट वर्ज़न**: {s.get('agent_version', '1.0.1')}\n\n"
                        f"क्या आप कोई नया वाउचर बनाना चाहते हैं या सिंक स्टेटस देखना चाहते हैं?"
                    )
                else:
                    reply = (
                        f"Aapka Tally Prime Connector for **{active_company}** abhi **{online_str.upper()}** hai!\n\n"
                        f"• **Active Port**: {port} (`{source}`)\n"
                        f"• **Company**: {active_company}\n"
                        f"• **Agent Version**: {s.get('agent_version', '1.0.1')}\n\n"
                        f"Kya aapko kisi ledger ka sync check karna hai ya naya voucher banana hai?"
                    )

            elif any(w in last_msg_lower for w in ["sync", "fail", "सिंक"]):
                s = await connector_client.get_connection_status(
                    company_name=active_company,
                    user_email=caller["email"],
                    preferred_port=caller["tally_port"],
                )
                sync_info = await connector_client.get_sync_status(active_company)
                err_list = await connector_client.get_sync_errors(active_company)
                port = s.get("tally_port", "Auto")
                sync_state = sync_info.get("status", "ACTIVE")
                synced_cnt = sync_info.get("synced_records", 0)
                total_cnt = sync_info.get("total_records", 0)
                err_cnt = len(err_list)

                if lang_code == "en-IN":
                    reply = (
                        f"Hello **{caller['name']}**, I have verified the live synchronization telemetry for **{active_company}**:\n\n"
                        f"• **Sync Status**: `{sync_state}` ({synced_cnt}/{total_cnt} vouchers synced)\n"
                        f"• **Company**: {active_company}\n"
                        f"• **Tally Port**: {port} (`{s.get('detection_source', 'LIVE')}`)\n"
                        f"• **Diagnostic Errors**: {err_cnt} synchronization errors detected.\n\n"
                        f"Let me know if you would like to queue a new voucher or raise a support ticket."
                    )
                elif lang_code == "hi-IN":
                    reply = (
                        f"नमस्ते **{caller['name']}**, मैंने **{active_company}** की लाइव सिंक स्थिति की जाँच कर ली है:\n\n"
                        f"• **सिंक स्टेटस**: `{sync_state}` ({synced_cnt}/{total_cnt} वाउचर सिंक हो चुके हैं)\n"
                        f"• **कंपनी**: {active_company}\n"
                        f"• **Tally पोर्ट**: {port} (`{s.get('detection_source', 'LIVE')}`)\n"
                        f"• **डायग्नोस्टिक एरर**: {err_cnt} सिंक एरर पाए गए।\n\n"
                        f"यदि आप कोई नया वाउचर सिंक करना चाहते हैं या सपोर्ट टिकट बनाना चाहते हैं, तो कृपया बताएं।"
                    )
                else:
                    reply = (
                        f"Namaste **{caller['name']}**, maine **{active_company}** ka live synchronization telemetry check kiya hai:\n\n"
                        f"• **Sync Status**: `{sync_state}` ({synced_cnt}/{total_cnt} vouchers synced)\n"
                        f"• **Company**: {active_company}\n"
                        f"• **Tally Port**: {port} (`{s.get('detection_source', 'LIVE')}`)\n"
                        f"• **Diagnostic Errors**: {err_cnt} synchronization errors found.\n\n"
                        f"Agar aapko koi naya voucher sync karna hai ya support ticket raise karna hai, toh batayein."
                    )

            elif knowledge_context:
                best_chunk = knowledge_context[0]
                if lang_code == "en-IN":
                    reply = (
                        f"Hello **{caller['name']}**, here is the official **CtrlBooks Guide ({best_chunk.get('title', 'Documentation')})** for **{active_company}**:\n\n"
                        f"{best_chunk.get('content', '')}\n\n"
                        f"Does this resolve your issue, or would you like me to execute a Tally command?"
                    )
                elif lang_code == "hi-IN":
                    reply = (
                        f"नमस्ते **{caller['name']}**, **{active_company}** के लिए **CtrlBooks गाइड ({best_chunk.get('title', 'Documentation')})** यहाँ दी गई है:\n\n"
                        f"{best_chunk.get('content', '')}\n\n"
                        f"क्या इससे आपकी समस्या हल हो गई, या मैं Tally में कोई कमांड चलाऊँ?"
                    )
                else:
                    reply = (
                        f"Namaste **{caller['name']}**, **{active_company}** ke liye **CtrlBooks Knowledge Base ({best_chunk.get('title', 'Official Guide')})**:\n\n"
                        f"{best_chunk.get('content', '')}\n\n"
                        f"Kya isse aapka issue solve hua, ya main Tally me koi action perform karun?"
                    )

            elif any(w in last_msg_lower for w in ["tds", "194c", "194j", "194q", "tax deducted"]):
                if lang_code == "en-IN":
                    reply = (
                        f"Hello **{caller['name']}**, here is the **TDS Compliance Reference for {active_company}**:\n\n"
                        "• **Section 194C (Contractors)**: 1% (Individual/HUF) | 2% (Company/Firm) | Threshold: ₹30,000 single / ₹1,00,000 aggregate.\n"
                        "• **Section 194J (Professional/Technical)**: 10% (Professional) | 2% (Technical) | Threshold: ₹30,000/FY.\n"
                        "• **Section 194I (Rent)**: 2% (Machinery) | 10% (Land/Building) | Threshold: ₹2,40,000/FY.\n"
                        "• **Section 194Q (Purchase of Goods)**: 0.1% above ₹50 Lakh (Turnover > ₹10 Cr).\n\n"
                        "Would you like me to queue a voucher or check a ledger in CtrlBooks?"
                    )
                elif lang_code == "hi-IN":
                    reply = (
                        f"नमस्ते **{caller['name']}**, **{active_company}** के लिए **TDS कम्प्लायंस विवरण** नीचे दिया गया है:\n\n"
                        "• **धारा 194C (कॉन्ट्रैक्टर)**: 1% (व्यक्ति/HUF) | 2% (कंपनी/फर्म) | सीमा: ₹30,000 एकल / ₹1,00,000 कुल।\n"
                        "• **धारा 194J (प्रोफेशनल/टेक्निकल)**: 10% (प्रोफेशनल) | 2% (टेक्निकल) | सीमा: ₹30,000 प्रति वर्ष।\n"
                        "• **धारा 194I (किराया/Rent)**: 2% (मशीनरी) | 10% (भूमि/भवन) | सीमा: ₹2,40,000 प्रति वर्ष।\n"
                        "• **धारा 194Q (माल की खरीद)**: ₹50 लाख से अधिक पर 0.1%।\n\n"
                        "आप किसी विशेष धारा के बारे में पूछ सकते हैं या नया वाउचर बनाने का निर्देश दे सकते हैं।"
                    )
                else:
                    reply = (
                        f"Namaste **{caller['name']}**, **{active_company}** ke liye **TDS Compliance Reference**:\n\n"
                        "• **194C (Contractors)**: 1% (Ind/HUF) / 2% (Company) | Limit: ₹30k single / ₹1 Lakh aggregate.\n"
                        "• **194J (Professional/Tech)**: 10% (Prof) / 2% (Tech) | Limit: ₹30k/yr.\n"
                        "• **194I (Rent)**: 2% (Machinery) / 10% (Building) | Limit: ₹2.4 Lakh/yr.\n"
                        "• **194Q (Goods Purchase)**: 0.1% above ₹50 Lakh.\n\n"
                        "Aap specific section pooch sakte hain ya voucher entry pass karne ke liye bol sakte hain."
                    )

            elif any(w in last_msg_lower for w in ["gst", "gstr", "hsn", "einvoice", "e-invoice", "eway", "e-way", "जीएसटी"]):
                if lang_code == "en-IN":
                    reply = (
                        f"Hello **{caller['name']}**, here is the **CtrlBooks GST & Compliance Guide for {active_company}**:\n\n"
                        "• **Supported GST Slabs in Voucher Engine**: `0%`, `5%`, `12%`, `18%`, `28%` (Auto-splits into Intra-State `CGST+SGST` or Inter-State `IGST`).\n"
                        "• **GSTR-1 Filing**: 11th of following month (13th for QRMP).\n"
                        "• **GSTR-3B Filing**: 20th of following month.\n"
                        "• **E-Invoice & E-Way Bill**: IRN mandatory above ₹5 Cr turnover; E-Way Bill above ₹50,000 consignment.\n\n"
                        f"Try: *'Create a sales invoice for {sample_party} of ₹25,000 at 12% GST'*"
                    )
                elif lang_code == "hi-IN":
                    reply = (
                        f"नमस्ते **{caller['name']}**, **{active_company}** के लिए **CtrlBooks GST और कम्प्लायंस जानकारी**:\n\n"
                        "• **डायनामिक GST स्लैब**: हमारा इंजन `0%`, `5%`, `12%`, `18%` और `28%` GST (`CGST+SGST` और `IGST`) की गणना स्वचालित रूप से करता है।\n"
                        "• **GSTR-1 / GSTR-3B तिथि**: हर महीने की 11 तारीख (GSTR-1) और 20 तारीख (GSTR-3B)।\n"
                        "• **ई-इनवॉइस और ई-वे बिल**: ₹5 करोड़+ टर्नओवर पर IRN और ₹50,000+ माल पर ई-वे बिल अनिवार्य है।\n\n"
                        f"उदाहरण: *'{sample_party} के लिए 25,000 का सेल्स इनवॉइस 12% GST के साथ बना दो'*"
                    )
                else:
                    reply = (
                        f"Namaste **{caller['name']}**, **{active_company}** ke liye **GST & Compliance Engine**:\n\n"
                        "• **Dynamic GST Slabs**: Humara engine `0%`, `5%`, `12%`, `18%`, aur `28%` GST (Intra-state `CGST+SGST` aur Inter-state `IGST`) dono automatically calculate karta hai.\n"
                        "• **GSTR-1 / 3B Dates**: Monthly 11th (GSTR-1) aur 20th (GSTR-3B).\n"
                        "• **E-Invoice / E-Way Bill**: ₹5 Crore+ turnover par IRN aur ₹50,000+ consignment par E-Way Bill.\n\n"
                        f"Try karein: *'{sample_party} ke liye 25,000 ka sales invoice 12% GST ke sath bana do'*"
                    )

            elif any(w in last_msg_lower for w in ["pending", "outstanding", "balance", "due", "receivable", "payable", "ledger", "बकाया", "बाकी", "लेजर"]):
                s = await connector_client.get_connection_status(
                    company_name=active_company,
                    user_email=caller["email"],
                    preferred_port=caller["tally_port"],
                )
                port = s.get("tally_port", "Auto")
                queued_cmds = command_queue_service.list_queued_commands()
                company_cmds = [c for c in queued_cmds if c.get("company") == active_company]
                total_queued_amt = sum(c.get("payload", {}).get("payload", {}).get("amount", 0.0) for c in company_cmds)

                if lang_code == "en-IN":
                    reply = (
                        f"Hello **{caller['name']}**, here is the **CtrlBooks Live Ledger & Queue Summary for {active_company}**:\n\n"
                        f"• **Active Company**: {active_company}\n"
                        f"• **Queued Vouchers for Tally**: {len(company_cmds)} pending\n"
                        f"• **Queued Total Value**: ₹{total_queued_amt:,.2f}\n"
                        f"• **Active Tally Port**: {port} (`{s.get('detection_source', 'LIVE')}`)\n\n"
                        f"Would you like to create a new sales/receipt voucher or check a specific party ledger?"
                    )
                elif lang_code == "hi-IN":
                    reply = (
                        f"नमस्ते **{caller['name']}**, **{active_company}** के लिए **CtrlBooks लाइव लेजर और बकाया सारांश**:\n\n"
                        f"• **सक्रिय कंपनी**: {active_company}\n"
                        f"• **Tally के लिए कतारबद्ध (Queued) वाउचर**: {len(company_cmds)} पेंडिंग\n"
                        f"• **कुल वाउचर राशि**: ₹{total_queued_amt:,.2f}\n"
                        f"• **सक्रिय Tally पोर्ट**: {port} (`{s.get('detection_source', 'LIVE')}`)\n\n"
                        f"क्या आप किसी पार्टी के लिए नया सेल्स या रसीद वाउचर बनाना चाहते हैं?"
                    )
                else:
                    reply = (
                        f"Namaste **{caller['name']}**, **{active_company}** ke liye **CtrlBooks Live Outstanding & Queue Summary**:\n\n"
                        f"• **Active Company**: {active_company}\n"
                        f"• **Queued Vouchers for Tally**: {len(company_cmds)} pending\n"
                        f"• **Queued Total Value**: ₹{total_queued_amt:,.2f}\n"
                        f"• **Active Tally Port**: {port} (`{s.get('detection_source', 'LIVE')}`)\n\n"
                        f"Kya aapko kisi party ke liye naya sales/receipt voucher banana hai?"
                    )

            else:
                if lang_code == "en-IN":
                    reply = (
                        f"Hello **{caller['name']}**! I am the **CtrlBooks AI Assistant** for **{active_company}**.\n\n"
                        f"You can speak or type in English, Hindi, Hinglish, Gujarati, Marathi, or Tamil:\n"
                        f"• *'Create a sales invoice for {sample_party} of ₹25,000 at 18% GST'*\n"
                        f"• *'Create a receipt voucher from {sample_party} for ₹15,000'*\n"
                        f"• *'Check live Tally Prime port and synchronization status'*"
                    )
                elif lang_code == "hi-IN":
                    reply = (
                        f"नमस्ते **{caller['name']}**! मैं **{active_company}** के लिए **CtrlBooks AI Assistant** हूँ।\n\n"
                        f"आप मुझसे हिंदी, इंग्लिश या हिंग्लिश में बोलकर या लिखकर काम करवा सकते हैं:\n"
                        f"• *'{sample_party} के लिए 25,000 का सेल्स इनवॉइस बना दो'*\n"
                        f"• *'{sample_party} से 15,000 की रसीद (Receipt) वाउचर बना दो'*\n"
                        f"• *'Tally सिंक स्टेटस और बकाया इनवॉइस दिखाओ'*"
                    )
                else:
                    reply = (
                        f"Namaste **{caller['name']}**! Main **{active_company}** ke liye **CtrlBooks AI Assistant** hoon.\n\n"
                        f"Aap mujhse kisi bhi language (English, Hindi, Hinglish, Gujarati, Marathi) me bol ya type kar sakte hain:\n"
                        f"• *'{sample_party} ke liye 25,000 ka sales invoice bana do'*\n"
                        f"• *'{sample_party} se 15,000 ka receipt voucher bana do'*\n"
                        f"• *'Tally sync status aur pending queue dikhao'*"
                    )

        clean_reply = _sanitize_brand_identity(reply)
        dynamic_usage = _estimate_token_usage(messages, clean_reply)
        return {
            "content": clean_reply,
            "tool_calls": executed_tools,
            "usage": dynamic_usage,
            "model": "patwatoliai-ctrlbooks-subassistant-v1",
            "detected_language": lang_name,
            "language_code": lang_code,
            "recommended_voice": recommended_voice,
        }


ai_gateway = AIGateway()
