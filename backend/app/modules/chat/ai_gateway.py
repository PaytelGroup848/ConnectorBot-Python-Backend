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
from app.modules.chat.handlers.ticket_handler import handle_ticket_status_check, handle_ticket_creation
from app.modules.chat.handlers.voucher_handler import handle_voucher_creation
from app.modules.chat.handlers.reports_handler import handle_accounting_reports
from app.modules.chat.handlers.sales_handler import handle_sales_analytics, handle_voucher_lookup
from app.modules.chat.handlers.cash_bank_handler import handle_cash_bank

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
        r"inventory|reports?|profit|loss|balance\s*sheet|trial\s*balance|trail\s*balance|day\s*book|daybook|pnl|gst|gstr|gstr1|gstr-1|gstr3b|"
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
        r"दिखाओ|देखो|दिखाना|जीएसटी|टैक्स|रिटर्न|टिकट|शिकायत|समस्या|एरर|नमस्ते|मदद|कंपनी|पोर्ट|टेली|रिपोर्ट|रिपोर्ट्स|डेबुक|डे\s*बुक|વાઉચર|ટેલી|જીએસટી|ટિકિટ)"
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
        slot_missing_reply = None
        is_check_ticket, t_tools, t_text, t_reply = await handle_ticket_status_check(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            db=db,
        )
        if is_check_ticket:
            executed_tools.extend(t_tools)
            tool_results_text += t_text
            if t_reply:
                slot_missing_reply = t_reply

        # 2. Check Support Ticket / Escalation Intent (Multilingual Corporate Intake)
        handled_ticket, tc_tools, tc_text, tc_reply = await handle_ticket_creation(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            db=db,
            conversation_id=conversation_id,
            ctx=ctx,
            lang_code=lang_code,
            lang_name=lang_name,
            messages=messages,
            is_check_ticket_intent=is_check_ticket,
        )
        if handled_ticket:
            executed_tools.extend(tc_tools)
            tool_results_text += tc_text
            if tc_reply:
                slot_missing_reply = tc_reply
        is_ticket_intent = handled_ticket


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

        # 4. Dynamic Voucher Intent & Slot Filling (Sales, Receipt, Payment, Purchase, Notes, Contra, Journal)
        handled_voucher, v_tools, v_text, v_reply = await handle_voucher_creation(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            ctx=ctx,
            lang_code=lang_code,
            lang_name=lang_name,
            sample_party=sample_party,
            today_date=today_date,
            is_ticket_intent=is_ticket_intent,
            extract_entities_fn=extract_voucher_entities,
        )
        if handled_voucher:
            executed_tools.extend(v_tools)
            tool_results_text += v_text
            if v_reply:
                slot_missing_reply = v_reply
        is_voucher_intent = handled_voucher


        # 4a. Dynamic Cash & Bank Module Intent (Cash in hand, Bank Accounts, Liquid Funds)
        handled_cash_bank, cb_tools, cb_text, cb_reply = await handle_cash_bank(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            lang_code=lang_code,
            is_ticket_intent=is_ticket_intent,
            is_voucher_intent=is_voucher_intent,
        )
        if handled_cash_bank:
            executed_tools.extend(cb_tools)
            tool_results_text += cb_text
            if cb_reply:
                slot_missing_reply = cb_reply
        is_cash_bank_intent = handled_cash_bank


        # 4b. Dynamic Official Accounting Reports Intent (Day Book, Trial Balance, P&L, Balance Sheet, Voucher Lines)
        handled_reports, r_tools, r_text, r_reply = await handle_accounting_reports(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            lang_code=lang_code,
            is_ticket_intent=is_ticket_intent,
            is_voucher_intent=is_voucher_intent,
            is_cash_bank_intent=is_cash_bank_intent,
        )
        if handled_reports:
            executed_tools.extend(r_tools)
            tool_results_text += r_text
            if r_reply:
                slot_missing_reply = r_reply
        is_accounting_reports_intent = handled_reports


        # 4c. Dynamic Sales & Financial Analytics / Summary Intent (Sales, Receipts, Orders, Credit Notes)
        handled_sales, s_tools, s_text, s_reply = await handle_sales_analytics(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            lang_code=lang_code,
            sample_party=sample_party,
            is_ticket_intent=is_ticket_intent,
            is_voucher_intent=is_voucher_intent,
            is_accounting_reports_intent=is_accounting_reports_intent,
            is_cash_bank_intent=is_cash_bank_intent,
        )
        if handled_sales:
            executed_tools.extend(s_tools)
            tool_results_text += s_text
            if s_reply:
                slot_missing_reply = s_reply
        is_sales_analytics_intent = handled_sales

        # 4c. Dynamic View/Lookup Voucher Intent (Fetches synced invoices/vouchers from Cloud/Tally)
        handled_vlookup, vl_tools, vl_text, vl_reply = await handle_voucher_lookup(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            lang_code=lang_code,
            today_date=today_date,
            is_ticket_intent=is_ticket_intent,
            is_voucher_intent=is_voucher_intent,
            is_sales_analytics_intent=is_sales_analytics_intent,
            is_cash_bank_intent=is_cash_bank_intent,
        )
        if handled_vlookup:
            executed_tools.extend(vl_tools)
            tool_results_text += vl_text
            if vl_reply:
                slot_missing_reply = vl_reply


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
                t["tool"] in ("create_support_ticket", "create_sales_invoice_command", "create_receipt_voucher_command", "get_sales_analytics_command", "get_accounting_report_command")
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
            report_tool = next((t for t in executed_tools if t["tool"] == "get_accounting_report_command"), None)
            analytics_tool = next((t for t in executed_tools if t["tool"] == "get_sales_analytics_command"), None)
            status_tool = next((t for t in executed_tools if t["tool"] == "check_support_ticket_status"), None)
            ticket_tool = next((t for t in executed_tools if t["tool"] == "create_support_ticket"), None)
            voucher_tool = next(
                (t for t in executed_tools if t["tool"] in ("create_sales_invoice_command", "create_receipt_voucher_command")),
                None,
            )
            if report_tool:
                r_res = report_tool["result"]
                rep_t = r_res.get("report_title", "Accounting Report")
                comp = r_res.get("company_name", active_company)
                cnt = r_res.get("total_count", 0)
                reply = (
                    f"📊 **{comp} — {rep_t}:**\n\n"
                    f"• **Total Entries / Records:** **{cnt}**\n\n"
                    f"Aapke liye interactive live accounting report card niche ready hai!"
                )
            elif analytics_tool:
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
