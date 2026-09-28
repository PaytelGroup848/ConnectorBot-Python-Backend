import re
from typing import Tuple, Dict


class PIIScrubber:
    """Anonymizes and scrubs PII (GSTIN, PAN, Phone, Bank details) before sending data to external AI models."""
    def __init__(self):
        # Compiled regex patterns for Indian accounting & personal data
        self.gstin_pattern = re.compile(r'\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}\b', re.IGNORECASE)
        self.pan_pattern = re.compile(r'\b[A-Z]{5}\d{4}[A-Z]{1}\b', re.IGNORECASE)
        self.phone_pattern = re.compile(r'\b(?:\+91[\-\s]?|91[\-\s]?|0)?[6-9]\d{9}\b')
        self.email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

    def scrub(self, text: str) -> Tuple[str, Dict[str, str]]:
        if not text:
            return text, {}

        scrubbed = text
        mapping: Dict[str, str] = {}
        counter = {"gstin": 0, "pan": 0, "phone": 0, "email": 0}

        # 1. Scrub GSTINs
        def replace_gstin(match):
            val = match.group(0)
            counter["gstin"] += 1
            tag = f"[MASKED_GSTIN_{counter['gstin']}]"
            mapping[tag] = val
            return tag
        scrubbed = self.gstin_pattern.sub(replace_gstin, scrubbed)

        # 2. Scrub PANs
        def replace_pan(match):
            val = match.group(0)
            counter["pan"] += 1
            tag = f"[MASKED_PAN_{counter['pan']}]"
            mapping[tag] = val
            return tag
        scrubbed = self.pan_pattern.sub(replace_pan, scrubbed)

        # 3. Scrub Phones
        def replace_phone(match):
            val = match.group(0)
            counter["phone"] += 1
            tag = f"[MASKED_PHONE_{counter['phone']}]"
            mapping[tag] = val
            return tag
        scrubbed = self.phone_pattern.sub(replace_phone, scrubbed)

        # 4. Scrub Emails
        def replace_email(match):
            val = match.group(0)
            counter["email"] += 1
            tag = f"[MASKED_EMAIL_{counter['email']}]"
            mapping[tag] = val
            return tag
        scrubbed = self.email_pattern.sub(replace_email, scrubbed)

        return scrubbed, mapping

    def restore(self, text: str, mapping: Dict[str, str]) -> str:
        """Restores masked values back to plaintext for authorized end-user UI display."""
        restored = text
        for tag, original_val in mapping.items():
            restored = restored.replace(tag, original_val)
        return restored


pii_scrubber = PIIScrubber()

