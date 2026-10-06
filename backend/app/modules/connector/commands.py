"""
Modular facade for CommandQueueService.
Inherits decomposed command handling across specialized domain mixins:
- BaseCommandQueue: Idempotency hashing, penny balancing, queue listing
- SalesCommandMixin: Sales invoices, service bills, receipts, credit notes, sales orders
- PurchaseCommandMixin: Purchase bills, vendor payments, debit notes, journal, contra, POs
- MasterCommandMixin: Customer, Supplier, Party Masters, Stock Items, Units, Voucher Deletion
"""

import logging
from app.modules.connector.command_modules.base import BaseCommandQueue
from app.modules.connector.command_modules.sales_commands import SalesCommandMixin
from app.modules.connector.command_modules.purchase_commands import PurchaseCommandMixin
from app.modules.connector.command_modules.master_commands import MasterCommandMixin

logger = logging.getLogger("connector_ai.commands")


class CommandQueueService(
    BaseCommandQueue,
    SalesCommandMixin,
    PurchaseCommandMixin,
    MasterCommandMixin,
):
    """
    Manages 2-way asynchronous command queuing to Tally Prime via CtrlBooks engine.
    Supports all 16 standardized CtrlBooks command envelope schemas.
    """
    pass


# Global singleton instance for 100% backward-compatibility
command_queue_service = CommandQueueService()

__all__ = [
    "CommandQueueService",
    "command_queue_service",
]
