import hashlib
import logging
from typing import Dict, Any, List

logger = logging.getLogger("connector_ai.commands")


class BaseCommandQueue:
    """Base queue storage, idempotency hashing, and Penny Balancing for accounting precision."""
    def __init__(self):
        self._idempotency_cache: Dict[str, Dict[str, Any]] = {}

    def _generate_command_hash(self, company_name: str, command_type: str, identifier: str) -> str:
        raw_key = f"{company_name}:{command_type}:{identifier}".strip().lower()
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def apply_penny_balancing(self, items: list, declared_total: float) -> list:
        """Compensates for floating-point rounding discrepancies to ensure zero ledger rejections."""
        calculated_total = sum(item.get("amount", 0.0) for item in items)
        diff = round(declared_total - calculated_total, 2)
        if diff != 0 and items:
            items[0]["amount"] = round(items[0]["amount"] + diff, 2)
        return items

    def list_queued_commands(self) -> list:
        """Returns all vouchers and commands currently waiting in the 2-way queue for Tally sync."""
        return list(self._idempotency_cache.values())

