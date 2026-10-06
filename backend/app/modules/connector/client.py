"""
Modular facade for ConnectorClient.
Inherits decomposed client capabilities across dedicated domain mixins:
- BaseConnectorClient: Connection pooling, port scanning, low-level HTTP requests
- CompanyClientMixin: Tally company discovery, ID resolution, voucher types, godowns
- VoucherClientMixin: Voucher queueing, Tally XML creation, direct push
- FinancialClientMixin: Sales, purchases, receipts, payments, credit/debit notes
- ReportsClientMixin: Day Book, Trial Balance, P&L, Balance Sheet, Voucher Lines
- PartiesClientMixin: Customer, vendor, bank, cash, and ledger operations
- TelemetryClientMixin: Cloud heartbeat, sync diagnostics, subscription status
"""

import logging
from app.modules.connector.client_modules.base import BaseConnectorClient, CANDIDATE_TALLY_PORTS
from app.modules.connector.client_modules.companies import CompanyClientMixin
from app.modules.connector.client_modules.vouchers import VoucherClientMixin
from app.modules.connector.client_modules.financial import FinancialClientMixin
from app.modules.connector.client_modules.reports import ReportsClientMixin
from app.modules.connector.client_modules.parties import PartiesClientMixin
from app.modules.connector.client_modules.telemetry import TelemetryClientMixin

logger = logging.getLogger("connector_ai.connector_client")


class ConnectorClient(
    BaseConnectorClient,
    CompanyClientMixin,
    VoucherClientMixin,
    FinancialClientMixin,
    ReportsClientMixin,
    PartiesClientMixin,
    TelemetryClientMixin,
):
    """Resilient client communicating with Connector / CtrlBooks APIs with dynamic Tally port auto-discovery."""
    pass


# Global singleton instance for 100% backward-compatibility across all modules
connector_client = ConnectorClient()

__all__ = [
    "ConnectorClient",
    "connector_client",
    "CANDIDATE_TALLY_PORTS",
]
