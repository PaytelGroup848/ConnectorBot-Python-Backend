"""Domain handlers for CtrlBooks AI Gateway."""

from .ticket_handler import handle_ticket_status_check, handle_ticket_creation
from .voucher_handler import handle_voucher_creation
from .reports_handler import handle_accounting_reports
from .sales_handler import handle_sales_analytics, handle_voucher_lookup
from .cash_bank_handler import handle_cash_bank
from .party_handler import handle_parties

__all__ = [
    "handle_ticket_status_check",
    "handle_ticket_creation",
    "handle_voucher_creation",
    "handle_accounting_reports",
    "handle_sales_analytics",
    "handle_voucher_lookup",
    "handle_cash_bank",
    "handle_parties",
]
