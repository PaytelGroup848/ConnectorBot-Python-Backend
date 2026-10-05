"""
CtrlBooks Enterprise Multilingual Linguistic Engine & Parser Utilities.

Handles:
- Zero-Click Automatic Language & Script Identification (Auto-LID) across 7 Indian languages
- Regional Unicode numeral normalization (Devanagari, Gujarati, Bengali, Tamil, Telugu, Kannada)
- Spoken multiplier expansion (hazar, lakh, crore)
- Entity extraction for voucher transactions (amounts, ledgers, tax rates, inter-state IGST)
- Domain guardrail enforcement for enterprise accounting
- Clean SaaS fallback & statutory reference synthesis
"""

import logging
import re
from typing import List, Dict, Any, Optional

from app.middleware.tenant_context import TenantContext
from app.modules.connector.commands import command_queue_service

logger = logging.getLogger("connector_ai.linguistics")

# Unicode digit translation table covering Devanagari, Gujarati, Bengali, Tamil, Telugu, Kannada -> ASCII 0-9
INDIAN_DIGIT_MAP = str.maketrans(
    "०१२३४५६७८९"  # Devanagari (Hindi / Marathi)
    "૦૧૨૩૪૫૬૭૮૯"  # Gujarati
    "০১২৩৪৫৬৭৮৯"  # Bengali
    "௦௧௨௩௪௫௬௭௮௯"  # Tamil
    "౦౧౨౩౪౫౬౭౮౯"  # Telugu
    "೦೧೨೩೪೫೬೭೮೯",  # Kannada
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
    raw_name = (meta.get("user_name") or "").strip()
    raw_uid = str(ctx.user_id or "")

    is_generic = (
        not raw_name
        or any(w in raw_name.lower() for w in ["authorized", "authenticated", "guest", "customer", "anonymous"])
        or raw_name.lower() in ("user", "")
    )
    clean_name = raw_name if not is_generic else ""
    default_email = raw_uid if "@" in raw_uid else f"{raw_uid or 'user'}@{active_company.lower().replace(' ', '')[:16] or 'tenant'}.ctrlbooks.com"

    return {
        "name": clean_name,
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


def _is_ctrlbooks_domain_query(text: str, messages: List[Dict[str, str]], active_company: str = "") -> bool:
    """
    Strictly validates whether the user query belongs to the CtrlBooks / Tally Prime / GST / Accounting / Support domain.
    Rejects general world knowledge, coding, sports, entertainment, politics, recipes, weather, etc.
    """
    sample = (text or "").strip().lower()
    if not sample:
        return True

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

    if active_company:
        clean_comp_words = [w.lower() for w in active_company.split() if len(w) >= 3 and w.lower() not in ("company", "ltd", "pvt")]
        if any(w in sample for w in clean_comp_words):
            return True

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
        r"sla|team|engineer|fix|solve|working|mismatch|company|agency|enterprise|trader|traders|firm|"
        r"dashboard|portal|widget|login|user|about|details|overview|baare|info|"
        r"dikhao|dekho|dekhna|show|get|view|fetch|list|display|banao|bna|create|generate|daal|karo|make|"
        r"f[1-9]|f1[0-2]|fn|alt|ctrl|shortcut|shortcuts|configuration|configure|feature|features|"
        r"kaam|kam|chal|chalta|karein|karna|kaise|kahan|kyun|kyu|nahi|help|madad|troubleshoot|"
        r"hi|hello|hey|namaste|namaskar|good\s+morning|good\s+afternoon|good\s+evening|thanks|thank\s+you|"
        r"shukriya|dhanyawad|who\s+are\s+you|kaun\s+ho|kisne\s+banaya|what\s+can\s+you\s+do)\b|"
        r"(?:₹|टैली|सिंक|वाउचर|इनवॉइस|बिल|रसीद|लेजर|पार्टी|बकाया|खाता|हिसाब|पेमेंट|बिक्री|खरीद|"
        r"दिखाओ|देखो|दिखाना|जीएसटी|टैक्स|रिटर्न|टिकट|शिकायत|समस्या|एरर|नमस्ते|मदद|कंपनी|पोर्ट|टेली|रिपोर्ट|रिपोर्ट्स|डेबुक|डे\s*बुक|વાઉચર|ટેલી|જીએસટી|ટિકિટ)"
    )
    if re.search(in_scope_pattern, sample, re.IGNORECASE):
        return True

    if len(messages) >= 2:
        return True

    return False


def _build_clean_fallback_reply(lang_code: str, caller_name: str, active_company: str) -> str:
    """Generates a clean, transparent SaaS fallback message informing the user what capabilities and APIs are supported."""
    first_name = caller_name.strip().split()[0] if caller_name and caller_name.strip() else ""
    comp_str = f"**{active_company}**" if active_company and active_company.lower() not in ("ctrlbooks", "default", "your company") else "aapke workspace"

    if lang_code == "en-IN":
        greet = f"Hello **{first_name}**!" if first_name else "Hello!"
        return (
            f"{greet} I couldn't find matching data for that query, or it's outside my current accounting capabilities.\n\n"
            f"Here is what I can directly fetch and do for {comp_str}:\n"
            f"• 📊 **Sales & Collections**: *'What is today\'s sales?'*, *'Show this month\'s collection'*, *'Credit notes'*\n"
            f"• 👥 **Parties & Ledgers**: *'Customer list dikhao'*, *'Check Sharma Traders balance'*, *'Outstandings'*\n"
            f"• 📑 **Accounting Reports**: *'Day book dikhao'*, *'Profit & Loss report'*, *'Trial balance'*, *'Balance sheet'*\n"
            f"• 🏢 **Companies & Profiles**: *'Companies list'*, *'Company details dikhao'*\n"
            f"• 🔄 **Tally Status & Plans**: *'Is Tally connected?'*, *'My subscription plan'*, *'Sync status'*\n"
            f"• 🎫 **Support Tickets**: *'Raise a ticket for sync error'*, *'Check ticket status'*\n\n"
            f"Would you like to ask something from these available features?"
        )
    elif lang_code == "hi-IN":
        greet = f"नमस्ते **{first_name} जी**!" if first_name else "नमस्ते!"
        return (
            f"{greet} माफ़ कीजिए, मुझे इसका डेटा नहीं मिला या यह मेरे अकाउंटिंग स्कोप में नहीं है।\n\n"
            f"मैं {comp_str} के लिए निम्नलिखित जानकारी तुरंत दे सकता हूँ:\n"
            f"• 📊 **सेल्स एवं कलेक्शन**: *'आज की बिक्री कितनी है'*, *'इस महीने का कलेक्शन'*, *'क्रेडिट नोट'*\n"
            f"• 👥 **पार्टी एवं लेजर्स**: *'कस्टमर लिस्ट दिखाओ'*, *'शर्मा ट्रेडर्स का बैलेंस'*, *'कुल आउटस्टैंडिंग'*\n"
            f"• 📑 **अकाउंटिंग रिपोर्ट्स**: *'डे बुक दिखाओ'*, *'प्रॉफ़िट एंड लॉस'*, *'ट्रायल बैलेंस'*, *'बैलेंस शीट'*\n"
            f"• 🏢 **कंपनी विवरण**: *'कंपनियों की लिस्ट'*, *'कंपनी की डिटेल्स दिखाओ'*\n"
            f"• 🔄 **टैली सिंक स्थिति**: *'टैली कनेक्ट है क्या'*, *'मेरा सब्सक्रिप्शन प्लान'*\n"
            f"• 🎫 **सपोर्ट टिकट**: *'सिंक समस्या के लिए टिकट बनाओ'*, *'टिकट स्टेटस'*\n\n"
            f"क्या आप इनमें से कोई सवाल पूछना चाहेंगे?"
        )
    else:  # Hinglish / Default
        greet = f"Namaste **{first_name} bhai**!" if first_name else "Namaste!"
        return (
            f"{greet} Maaf kijiye, mujhe iska data nahi mila ya yeh mere accounting scope me abhi uplabdh nahi hai.\n\n"
            f"Main {comp_str} ke liye in topics par turant madad kar sakta hoon:\n"
            f"• 📊 **Sales & Receipts**: *'Aaj ka sales kitna hai'*, *'Is mahine ka collection'*, *'Credit notes'*\n"
            f"• 👥 **Parties & Ledgers**: *'Customer list dikhao'*, *'Sharma Traders ka balance'*, *'Mera outstanding'*\n"
            f"• 📑 **Accounting Reports**: *'Day book dikhao'*, *'Profit & Loss'*, *'Trial balance'*, *'Balance sheet'*\n"
            f"• 🏢 **Company Details**: *'Companies list'*, *'Company details dikhao'*\n"
            f"• 🔄 **Tally Status & Plans**: *'Tally chal raha hai kya?'*, *'Mera subscription plan'*\n"
            f"• 🎫 **Support Tickets**: *'Sync issue ke liye ticket raise karo'*, *'Ticket status check karo'*\n\n"
            f"Aap inme se koi specific sawal poochna chahenge?"
        )


def _build_domain_refusal_reply(lang_code: str, caller_name: str, active_company: str) -> str:
    """Generates clean, helpful fallback response guiding user to supported accounting capabilities."""
    return _build_clean_fallback_reply(lang_code, caller_name, active_company)


def _get_statutory_reference(
    last_msg_lower: str,
    lang_code: str,
    caller_name: str,
    active_company: str,
    sample_party: str,
) -> Optional[str]:
    """Provides instant, verified TDS and GST compliance references when offline or in fallback mode."""
    caller_first = caller_name.strip().split()[0] if caller_name and caller_name.strip() else ""

    if any(w in last_msg_lower for w in ["tds", "194c", "194j", "194q", "tax deducted"]):
        if lang_code == "en-IN":
            greet = f"Hello **{caller_first}**" if caller_first else "Hello"
            return (
                f"{greet}, here is the **TDS Compliance Reference for {active_company}**:\n\n"
                "• **Section 194C (Contractors)**: 1% (Individual/HUF) | 2% (Company/Firm) | Threshold: ₹30,000 single / ₹1,00,000 aggregate.\n"
                "• **Section 194J (Professional/Technical)**: 10% (Professional) | 2% (Technical) | Threshold: ₹30,000/FY.\n"
                "• **Section 194I (Rent)**: 2% (Machinery) | 10% (Land/Building) | Threshold: ₹2,40,000/FY.\n"
                "• **Section 194Q (Purchase of Goods)**: 0.1% above ₹50 Lakh (Turnover > ₹10 Cr).\n\n"
                "Would you like me to queue a voucher or check a ledger in CtrlBooks?"
            )
        elif lang_code == "hi-IN":
            greet = f"नमस्ते **{caller_first} जी**" if caller_first else "नमस्ते"
            return (
                f"{greet}, **{active_company}** के लिए **TDS कम्प्लायंस विवरण** नीचे दिया गया है:\n\n"
                "• **धारा 194C (कॉन्ट्रैक्टर)**: 1% (व्यक्ति/HUF) | 2% (कंपनी/फर्म) | सीमा: ₹30,000 एकल / ₹1,00,000 कुल।\n"
                "• **धारा 194J (प्रोफेशनल/टेक्निकल)**: 10% (प्रोफेशनल) | 2% (टेक्निकल) | सीमा: ₹30,000 प्रति वर्ष।\n"
                "• **धारा 194I (किराया/Rent)**: 2% (मशीनरी) | 10% (भूमि/भवन) | सीमा: ₹2,40,000 प्रति वर्ष।\n"
                "• **धारा 194Q (माल की खरीद)**: ₹50 लाख से अधिक पर 0.1%।\n\n"
                "आप किसी विशेष धारा के बारे में पूछ सकते हैं या नया वाउचर बनाने का निर्देश दे सकते हैं।"
            )
        else:
            greet = f"Namaste **{caller_first} ji**" if caller_first else "Namaste"
            return (
                f"{greet}, **{active_company}** ke liye **TDS Compliance Reference**:\n\n"
                "• **194C (Contractors)**: 1% (Ind/HUF) / 2% (Company) | Limit: ₹30k single / ₹1 Lakh aggregate.\n"
                "• **194J (Professional/Tech)**: 10% (Prof) / 2% (Tech) | Limit: ₹30k/yr.\n"
                "• **194I (Rent)**: 2% (Machinery) / 10% (Building) | Limit: ₹2.4 Lakh/yr.\n"
                "• **194Q (Goods Purchase)**: 0.1% above ₹50 Lakh.\n\n"
                "Aap specific section pooch sakte hain ya voucher entry pass karne ke liye bol sakte hain."
            )

    if any(w in last_msg_lower for w in ["gst", "gstr", "hsn", "einvoice", "e-invoice", "eway", "e-way", "जीएसटी"]):
        if lang_code == "en-IN":
            greet = f"Hello **{caller_first}**" if caller_first else "Hello"
            return (
                f"{greet}, here is the **CtrlBooks GST & Compliance Guide for {active_company}**:\n\n"
                "• **Supported GST Slabs in Voucher Engine**: `0%`, `5%`, `12%`, `18%`, `28%` (Auto-splits into Intra-State `CGST+SGST` or Inter-State `IGST`).\n"
                "• **GSTR-1 Filing**: 11th of following month (13th for QRMP).\n"
                "• **GSTR-3B Filing**: 20th of following month.\n"
                "• **E-Invoice & E-Way Bill**: IRN mandatory above ₹5 Cr turnover; E-Way Bill above ₹50,000 consignment.\n\n"
                f"Try: *'Create a sales invoice for {sample_party} of ₹25,000 at 12% GST'*"
            )
        elif lang_code == "hi-IN":
            greet = f"नमस्ते **{caller_first} जी**" if caller_first else "नमस्ते"
            return (
                f"{greet}, **{active_company}** के लिए **CtrlBooks GST और कम्प्लायंस जानकारी**:\n\n"
                "• **डायनामिक GST स्लैब**: हमारा इंजन `0%`, `5%`, `12%`, `18%` और `28%` GST (`CGST+SGST` और `IGST`) की गणना स्वचालित रूप से करता है।\n"
                "• **GSTR-1 / GSTR-3B तिथि**: हर महीने की 11 तारीख (GSTR-1) और 20 तारीख (GSTR-3B)।\n"
                "• **ई-इनवॉइस और ई-वे बिल**: ₹5 करोड़+ टर्नओवर पर IRN और ₹50,000+ माल पर ई-वे बिल अनिवार्य है।\n\n"
                f"उदाहरण: *'{sample_party} के लिए 25,000 का सेल्स इनवॉइस 12% GST के साथ बना दो'*"
            )
        else:
            greet = f"Namaste **{caller_first} ji**" if caller_first else "Namaste"
            return (
                f"{greet}, **{active_company}** ke liye **GST & Compliance Engine**:\n\n"
                "• **Dynamic GST Slabs**: Humara engine `0%`, `5%`, `12%`, `18%`, aur `28%` GST (Intra-state `CGST+SGST` aur Inter-state `IGST`) dono automatically calculate karta hai.\n"
                "• **GSTR-1 / 3B Dates**: Monthly 11th (GSTR-1) aur 20th (GSTR-3B).\n"
                "• **E-Invoice / E-Way Bill**: ₹5 Crore+ turnover par IRN aur ₹50,000+ consignment par E-Way Bill.\n\n"
                f"Try karein: *'{sample_party} ke liye 25,000 ka sales invoice 12% GST ke sath bana do'*"
            )

    return None


__all__ = [
    "INDIAN_DIGIT_MAP",
    "normalize_indian_numerals",
    "detect_language_and_script",
    "extract_voucher_entities",
    "_resolve_caller_identity",
    "_discover_sample_party",
    "_estimate_token_usage",
    "_sanitize_brand_identity",
    "_is_ctrlbooks_domain_query",
    "_build_clean_fallback_reply",
    "_build_domain_refusal_reply",
    "_get_statutory_reference",
]
