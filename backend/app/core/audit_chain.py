import hashlib
import json
from typing import List, Dict, Any, Tuple, Optional

GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"


class CryptographicAuditChain:
    """Provides tamper-proof Merkle/Blockchain-style hash chaining for security audit logs."""
    def __init__(self):
        self._last_hash = GENESIS_HASH

    def calculate_event_hash(
        self,
        event_type: str,
        actor_id: Optional[str],
        timestamp_str: str,
        metadata: Optional[Dict[str, Any]] = None,
        prev_hash: Optional[str] = None,
    ) -> str:
        parent_hash = prev_hash or self._last_hash
        payload_str = json.dumps(metadata or {}, sort_keys=True)
        raw_string = f"{parent_hash}|{event_type}|{actor_id or ''}|{timestamp_str}|{payload_str}"
        curr_hash = hashlib.sha256(raw_string.encode("utf-8")).hexdigest()
        self._last_hash = curr_hash
        return curr_hash

    def verify_chain_integrity(self, chain_records: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
        """Verifies cryptographic hash chain. Returns (True, None) if intact, (False, record_id) if tampered."""
        expected_prev = GENESIS_HASH
        for idx, rec in enumerate(chain_records):
            prev_in_rec = rec.get("prev_hash", GENESIS_HASH)
            if prev_in_rec != expected_prev:
                return False, f"Broken chain link at index {idx} (ID: {rec.get('id')})"

            computed = self.calculate_event_hash(
                event_type=rec["event_type"],
                actor_id=rec.get("actor_id"),
                timestamp_str=rec["timestamp"],
                metadata=rec.get("metadata"),
                prev_hash=expected_prev,
            )
            if computed != rec.get("curr_hash"):
                return False, f"Tampered record detected at index {idx} (ID: {rec.get('id')})"

            expected_prev = rec.get("curr_hash")

        return True, None


audit_chain = CryptographicAuditChain()

