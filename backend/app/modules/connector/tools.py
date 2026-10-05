import datetime
from typing import Dict, Any, List
from app.modules.connector.client import connector_client
from app.modules.connector.commands import command_queue_service
from app.middleware.tenant_context import TenantContext


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_my_connection_status",
            "description": "Checks live connection status of Tally Prime and the Connector desktop agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "connection_id": {"type": "string", "description": "Optional specific connection ID"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_connector_status_command",
            "description": "Fetches centralized cloud connector telemetry, registered device status, and lastSync progress.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Optional company name filter"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_subscription_status_command",
            "description": "Fetches active SaaS subscription details, plan name, validity dates, total seats, and active features.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_sync_status",
            "description": "Checks the current and last sync progress, synced records count, and status for a Tally company.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_sync_errors",
            "description": "Retrieves recent synchronization error logs and diagnostics for troubleshooting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_tally_connections",
            "description": "Lists all connected Tally companies and serial numbers linked to the current user's account.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_details_command",
            "description": "Fetches verified live Tally company profile, Company ID, Tally GUID, connection status, and synchronization metadata.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_id": {"type": "string", "description": "Optional specific CtrlBooks Company ID"},
                    "company_name": {"type": "string", "description": "Optional Tally company name"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_ledger",
            "description": "Searches for customer, vendor, or account ledgers in Tally (balance, GSTIN, phone).",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "query": {"type": "string", "description": "Search term for the party or ledger name"},
                },
                "required": ["company_name", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_stock_item",
            "description": "Searches for inventory product stock, closing quantity, standard rate, and HSN code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "query": {"type": "string", "description": "Product or item name"},
                },
                "required": ["company_name", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_vouchers_command",
            "description": "Retrieves real-time synchronized vouchers and invoices for a company from Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "voucher_type": {"type": "string", "description": "Sales, Receipt, Payment, Purchase, etc."},
                    "voucher_number": {"type": "string", "description": "Specific invoice/voucher number"},
                    "search": {"type": "string", "description": "Party or text search term"},
                    "limit": {"type": "number", "description": "Max vouchers to return (default: 5)"},
                },
            },
        },
    },
    # 1. Sales Invoice (Item / Inventory)
    {
        "type": "function",
        "function": {
            "name": "create_sales_invoice_command",
            "description": "Queues an item-based sales tax invoice with GST in Tally Prime via CtrlBooks engine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "party_ledger": {"type": "string", "description": "Customer party name"},
                    "date": {"type": "string", "description": "Invoice date (YYYY-MM-DD)"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "itemName": {"type": "string"},
                                "quantity": {"type": "number"},
                                "rate": {"type": "number"},
                                "units": {"type": "string"},
                                "amount": {"type": "number"},
                                "hsnCode": {"type": "string"},
                                "godown": {"type": "string"},
                            },
                        },
                    },
                    "total_amount": {"type": "number", "description": "Taxable subtotal"},
                    "sales_ledger": {"type": "string", "description": "Sales ledger (default: Sales)"},
                    "gst_rate": {"type": "number", "description": "GST % slab (0, 5, 12, 18, 28)"},
                    "is_igst": {"type": "boolean", "description": "True if inter-state IGST"},
                    "narration": {"type": "string", "description": "Narration"},
                },
                "required": ["company_name", "party_ledger", "total_amount"],
            },
        },
    },
    # 2. Service Sales Invoice (Accounting Only)
    {
        "type": "function",
        "function": {
            "name": "create_service_invoice_command",
            "description": "Queues a service/accounting sales invoice without inventory items.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "party_ledger": {"type": "string", "description": "Customer party name"},
                    "amount": {"type": "number", "description": "Total invoice amount"},
                    "date": {"type": "string", "description": "Invoice date (YYYY-MM-DD)"},
                    "service_income_ledger": {"type": "string", "description": "Income ledger (e.g. Consultancy Income)"},
                    "narration": {"type": "string", "description": "Narration"},
                    "gst_rate": {"type": "number", "description": "GST rate %"},
                },
                "required": ["company_name", "party_ledger", "amount"],
            },
        },
    },
    # 3. Receipt Voucher
    {
        "type": "function",
        "function": {
            "name": "create_receipt_voucher_command",
            "description": "Queues a customer payment receipt entry in Tally Prime via CtrlBooks engine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "party_ledger": {"type": "string", "description": "Customer party name"},
                    "bank_or_cash_ledger": {"type": "string", "description": "Bank or Cash account", "default": "Bank Account"},
                    "amount": {"type": "number", "description": "Receipt payment amount in INR"},
                    "date": {"type": "string", "description": "Receipt date (YYYY-MM-DD)"},
                    "payment_mode": {"type": "string", "description": "Cash, Cheque, NEFT, RTGS, UPI"},
                    "cheque_number": {"type": "string", "description": "Cheque or UTR number"},
                    "reference_no": {"type": "string", "description": "Reference number"},
                },
                "required": ["company_name", "party_ledger", "amount"],
            },
        },
    },
    # 4. Payment Voucher
    {
        "type": "function",
        "function": {
            "name": "create_payment_voucher_command",
            "description": "Queues a vendor payment or expense entry in Tally Prime via CtrlBooks engine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "party_ledger": {"type": "string", "description": "Vendor / Supplier party name"},
                    "bank_or_cash_ledger": {"type": "string", "description": "Bank or Cash account", "default": "Bank Account"},
                    "amount": {"type": "number", "description": "Payment amount in INR"},
                    "date": {"type": "string", "description": "Payment date (YYYY-MM-DD)"},
                    "payment_mode": {"type": "string", "description": "Cheque, NEFT, RTGS, Cash, UPI"},
                    "cheque_number": {"type": "string", "description": "Cheque or UTR number"},
                },
                "required": ["company_name", "party_ledger", "amount"],
            },
        },
    },
    # 5. Purchase Invoice
    {
        "type": "function",
        "function": {
            "name": "create_purchase_invoice_command",
            "description": "Queues a supplier purchase bill / inward goods voucher with GST in Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "party_ledger": {"type": "string", "description": "Supplier / Vendor name"},
                    "date": {"type": "string", "description": "Invoice date (YYYY-MM-DD)"},
                    "total_amount": {"type": "number", "description": "Taxable subtotal or total bill amount"},
                    "purchase_ledger": {"type": "string", "description": "Purchase account ledger (default: Purchase)"},
                    "supplier_invoice_no": {"type": "string", "description": "Vendor's original invoice number"},
                    "gst_rate": {"type": "number", "description": "GST rate %"},
                    "items": {"type": "array", "description": "Item details"},
                },
                "required": ["company_name", "party_ledger", "total_amount"],
            },
        },
    },
    # 6. Credit Note
    {
        "type": "function",
        "function": {
            "name": "create_credit_note_command",
            "description": "Queues a Credit Note (Sales Return) in Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "party_ledger": {"type": "string", "description": "Customer party name"},
                    "amount": {"type": "number", "description": "Credit Note value"},
                    "date": {"type": "string", "description": "Date (YYYY-MM-DD)"},
                    "original_invoice_no": {"type": "string", "description": "Original sales invoice number"},
                    "reason": {"type": "string", "description": "Reason for return/credit"},
                },
                "required": ["company_name", "party_ledger", "amount"],
            },
        },
    },
    # 7. Debit Note
    {
        "type": "function",
        "function": {
            "name": "create_debit_note_command",
            "description": "Queues a Debit Note (Purchase Return) in Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "party_ledger": {"type": "string", "description": "Supplier / Vendor name"},
                    "amount": {"type": "number", "description": "Debit Note value"},
                    "date": {"type": "string", "description": "Date (YYYY-MM-DD)"},
                    "original_invoice_no": {"type": "string", "description": "Original purchase invoice number"},
                    "reason": {"type": "string", "description": "Reason for return/debit"},
                },
                "required": ["company_name", "party_ledger", "amount"],
            },
        },
    },
    # 8. Journal
    {
        "type": "function",
        "function": {
            "name": "create_journal_command",
            "description": "Queues a Journal Voucher for adjustments, provisions, or depreciation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "amount": {"type": "number", "description": "Total journal amount"},
                    "narration": {"type": "string", "description": "Narration / reason"},
                    "date": {"type": "string", "description": "Date (YYYY-MM-DD)"},
                    "ledger_entries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ledgerName": {"type": "string"},
                                "amount": {"type": "number"},
                                "isDebit": {"type": "boolean"},
                            },
                        },
                    },
                },
                "required": ["company_name", "amount", "narration"],
            },
        },
    },
    # 9. Contra
    {
        "type": "function",
        "function": {
            "name": "create_contra_command",
            "description": "Queues a Contra Voucher (Cash deposit/withdrawal or bank transfer).",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "from_account": {"type": "string", "description": "Source account (e.g. Cash)"},
                    "to_account": {"type": "string", "description": "Destination account (e.g. Bank)"},
                    "amount": {"type": "number", "description": "Transfer amount"},
                    "date": {"type": "string", "description": "Date (YYYY-MM-DD)"},
                    "transaction_type": {"type": "string", "description": "Deposit, Withdrawal, or Transfer"},
                },
                "required": ["company_name", "from_account", "to_account", "amount"],
            },
        },
    },
    # 10. Sales Order
    {
        "type": "function",
        "function": {
            "name": "create_sales_order_command",
            "description": "Queues a Sales Order received from a customer in Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "party_ledger": {"type": "string", "description": "Customer party name"},
                    "total_amount": {"type": "number", "description": "Order value"},
                    "order_no": {"type": "string", "description": "Order number / PO ref"},
                    "due_date": {"type": "string", "description": "Delivery due date"},
                    "date": {"type": "string", "description": "Order date (YYYY-MM-DD)"},
                },
                "required": ["company_name", "party_ledger", "total_amount"],
            },
        },
    },
    # 11. Purchase Order
    {
        "type": "function",
        "function": {
            "name": "create_purchase_order_command",
            "description": "Queues a Purchase Order placed with a supplier in Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "party_ledger": {"type": "string", "description": "Supplier party name"},
                    "total_amount": {"type": "number", "description": "Order value"},
                    "order_no": {"type": "string", "description": "PO number"},
                    "due_date": {"type": "string", "description": "Delivery due date"},
                    "date": {"type": "string", "description": "Order date (YYYY-MM-DD)"},
                },
                "required": ["company_name", "party_ledger", "total_amount"],
            },
        },
    },
    # 12. Create Customer Master
    {
        "type": "function",
        "function": {
            "name": "create_customer_command",
            "description": "Creates a new Customer (Sundry Debtors) ledger master in Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "name": {"type": "string", "description": "Customer business or person name"},
                    "gstin": {"type": "string", "description": "15-digit GSTIN"},
                    "state": {"type": "string", "description": "State name"},
                    "phone": {"type": "string", "description": "Phone / Mobile number"},
                    "email": {"type": "string", "description": "Email address"},
                    "address": {"type": "string", "description": "Office / Factory address"},
                    "credit_days": {"type": "number", "description": "Credit period in days (default: 30)"},
                },
                "required": ["company_name", "name"],
            },
        },
    },
    # 13. Create Supplier Master
    {
        "type": "function",
        "function": {
            "name": "create_supplier_command",
            "description": "Creates a new Supplier / Vendor (Sundry Creditors) ledger master in Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "name": {"type": "string", "description": "Supplier business or person name"},
                    "gstin": {"type": "string", "description": "15-digit GSTIN"},
                    "state": {"type": "string", "description": "State name"},
                    "phone": {"type": "string", "description": "Phone / Mobile number"},
                    "email": {"type": "string", "description": "Email address"},
                    "address": {"type": "string", "description": "Supplier address"},
                    "credit_days": {"type": "number", "description": "Credit period in days (default: 45)"},
                },
                "required": ["company_name", "name"],
            },
        },
    },
    # 14. Create Stock Item Master
    {
        "type": "function",
        "function": {
            "name": "create_stock_item_command",
            "description": "Creates a new Inventory Product / Stock Item master in Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "name": {"type": "string", "description": "Item / Product name"},
                    "units": {"type": "string", "description": "Base unit (e.g. NOS, KGS, BOX)"},
                    "hsn_code": {"type": "string", "description": "HSN Code"},
                    "gst_rate": {"type": "number", "description": "GST rate % (e.g. 18)"},
                    "opening_qty": {"type": "number", "description": "Opening quantity"},
                    "opening_rate": {"type": "number", "description": "Opening rate per unit"},
                },
                "required": ["company_name", "name"],
            },
        },
    },
    # 15. Create Unit Master
    {
        "type": "function",
        "function": {
            "name": "create_unit_command",
            "description": "Creates a new Unit of Measurement (UOM) in Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "symbol": {"type": "string", "description": "Unit symbol (e.g. BOX, KGS, PCS)"},
                    "formal_name": {"type": "string", "description": "Formal name (e.g. Boxes, Kilograms)"},
                },
                "required": ["company_name", "symbol", "formal_name"],
            },
        },
    },
    # 16. Delete Voucher
    {
        "type": "function",
        "function": {
            "name": "delete_voucher_command",
            "description": "Cancels / Deletes an existing voucher in CtrlBooks & Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "voucher_type": {"type": "string", "description": "Sales, Purchase, Receipt, Payment, etc."},
                    "voucher_number": {"type": "string", "description": "Voucher number to delete"},
                    "date": {"type": "string", "description": "Voucher date (YYYY-MM-DD)"},
                    "reason": {"type": "string", "description": "Reason for cancellation"},
                },
                "required": ["company_name", "voucher_type", "voucher_number"],
            },
        },
    },
    # Legacy alias
    {
        "type": "function",
        "function": {
            "name": "create_ledger_master_command",
            "description": "Creates a customer or vendor ledger master in Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "party_name": {"type": "string", "description": "Customer or vendor name"},
                    "parent": {"type": "string", "description": "Sundry Debtors or Sundry Creditors", "default": "Sundry Debtors"},
                    "gstin": {"type": "string", "description": "15-character GSTIN"},
                    "state": {"type": "string", "description": "State name"},
                    "mobile": {"type": "string", "description": "10-digit mobile number"},
                },
                "required": ["company_name", "party_name"],
            },
        },
    },
    # 17. Fetch Vouchers
    {
        "type": "function",
        "function": {
            "name": "get_company_vouchers_command",
            "description": "Fetches and views real-time synced vouchers from Tally Prime / CtrlBooks Cloud API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "voucher_type": {"type": "string", "description": "Sales, Purchase, Receipt, etc."},
                    "voucher_number": {"type": "string", "description": "Specific voucher number to lookup"},
                    "search": {"type": "string", "description": "Party name or reference search query"},
                    "limit": {"type": "number", "description": "Max vouchers to return (default: 5)"},
                },
            },
        },
    },
    # 18. Sales & Financial Module Analytics
    {
        "type": "function",
        "function": {
            "name": "get_sales_analytics_command",
            "description": "Retrieves real-time analytics and transaction lists for Sales, Credit Notes, Receipts, Sales Orders, or Payments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "module": {"type": "string", "description": "sales, credit-notes, receipts, sales-orders, or payments"},
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "company_id": {"type": "string", "description": "Optional specific Company ID"},
                    "q": {"type": "string", "description": "Search query filter (party or voucher number)"},
                    "from_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                    "to_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                    "page": {"type": "number", "description": "Page number (default: 1)"},
                    "limit": {"type": "number", "description": "Max records (default: 20)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_payments_command",
            "description": "Retrieves real-time outgoing payment vouchers and records made to vendors, suppliers, or expense accounts from Tally Prime via CtrlBooks Cloud API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "company_id": {"type": "string", "description": "Optional specific Company ID"},
                    "q": {"type": "string", "description": "Search query filter (vendor name, party name, or voucher number)"},
                    "from_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                    "to_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                    "page": {"type": "number", "description": "Page number (default: 1)"},
                    "limit": {"type": "number", "description": "Max records (default: 10)"},
                },
            },
        },
    },
    # 19. Official Accounting Reports (Day Book, Trial Balance, P&L, Balance Sheet, Voucher Lines)
    {
        "type": "function",
        "function": {
            "name": "get_accounting_report_command",
            "description": "Retrieves official accounting reports: Day Book, Trial Balance, Profit & Loss, Balance Sheet, or Voucher Lines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_type": {"type": "string", "description": "day-book, trial-balance, pnl, balance-sheet, voucher-lines"},
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "company_id": {"type": "string", "description": "Optional specific Company ID"},
                    "from_date": {"type": "string", "description": "Start date for Day Book (YYYY-MM-DD)"},
                    "to_date": {"type": "string", "description": "End date for Day Book (YYYY-MM-DD)"},
                    "q": {"type": "string", "description": "Search query filter"},
                    "group": {"type": "string", "description": "Ledger group filter for Trial Balance (e.g. Sundry Debtors)"},
                    "ledger_type": {"type": "string", "description": "Ledger type for P&L or Balance Sheet (income/expense/asset/liability)"},
                    "voucher_id": {"type": "string", "description": "Voucher ID for voucher-lines report"},
                    "page": {"type": "number", "description": "Page number (default: 1)"},
                    "limit": {"type": "number", "description": "Max records (default: 50)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cash_bank_command",
            "description": "Retrieves real-time Cash in hand and Bank account balances, ledgers, and liquid fund positions from Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "company_id": {"type": "string", "description": "Optional specific Company ID"},
                    "account_type": {"type": "string", "description": "cash, bank, or both", "enum": ["cash", "bank", "both"]},
                    "q": {"type": "string", "description": "Search term for specific bank name e.g. HDFC, SBI, ICICI"},
                    "page": {"type": "number", "description": "Page number (default: 1)"},
                    "limit": {"type": "number", "description": "Max accounts to return (default: 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_parties_command",
            "description": "Retrieves real-time customer and supplier party ledger balances, outstandings, GSTIN, and contact details from Tally Prime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "company_id": {"type": "string", "description": "Optional specific Company ID"},
                    "q": {"type": "string", "description": "Optional party name search term (e.g. Microns, Steel, Trader)"},
                    "page": {"type": "number", "description": "Page number (default: 1)"},
                    "limit": {"type": "number", "description": "Max parties to return (default: 50)"},
                },
            },
        },
    },
]


async def execute_tool(tool_name: str, args: Dict[str, Any], ctx: TenantContext) -> Dict[str, Any]:
    """Executes a whitelisted tool with server-side tenant isolation enforcement."""
    today_date = datetime.date.today().isoformat()

    if tool_name == "get_my_connection_status":
        return await connector_client.get_connection_status(
            connection_id=args.get("connection_id"),
            company_name=args.get("company_name"),
            user_email=args.get("user_email"),
            preferred_port=args.get("tally_port"),
        )
    elif tool_name == "get_connector_status_command":
        token = args.get("connector_token") or args.get("token")
        cloud_status = await connector_client.get_cloud_connector_status(token=token)
        local_status = await connector_client.get_connection_status(
            company_name=args.get("company_name"),
            user_email=args.get("user_email"),
            preferred_port=args.get("tally_port"),
        )
        return {
            "success": True,
            "company_name": args.get("company_name", "CtrlBooks"),
            "cloud_status": cloud_status,
            "local_status": local_status,
            "latest_device": cloud_status.get("latest_connector"),
            "last_sync": cloud_status.get("last_sync"),
            "total_devices": cloud_status.get("total_connectors", 0),
        }
    elif tool_name == "get_subscription_status_command":
        token = args.get("connector_token") or args.get("token")
        return await connector_client.get_my_subscription(token=token)
    elif tool_name == "get_my_sync_status":
        return await connector_client.get_sync_status(args.get("company_name"))
    elif tool_name == "get_my_sync_errors":
        return {"errors": await connector_client.get_sync_errors(args.get("company_name"))}
    elif tool_name == "get_my_tally_connections":
        token = args.get("connector_token") or args.get("token")
        return {"connections": await connector_client.get_companies(token=token)}
    elif tool_name == "get_company_details_command":
        token = args.get("connector_token") or args.get("token")
        cid = args.get("company_id")
        cname = args.get("company_name")
        if not cid and cname:
            resolved = await connector_client.resolve_company_details(company_name=cname, token=token)
            cid = resolved.get("company_id")
        details = await connector_client.get_company_by_id(company_id=cid, token=token)
        return {"company": details, "company_id": cid}
    elif tool_name == "search_ledger":
        return {
            "ledgers": await connector_client.search_ledgers(
                company_name=args.get("company_name", ""),
                query=args.get("query", ""),
                company_id=args.get("company_id"),
                token=args.get("connector_token"),
            )
        }
    elif tool_name == "search_stock_item":
        return {"items": await connector_client.search_stock_items(args.get("company_name", ""), args.get("query", ""))}
    elif tool_name == "get_company_vouchers_command":
        vouchers = await connector_client.get_company_vouchers(
            company_name=args.get("company_name"),
            company_id=args.get("company_id"),
            voucher_type=args.get("voucher_type"),
            voucher_number=args.get("voucher_number"),
            search=args.get("search") or args.get("party_ledger"),
            limit=int(args.get("limit") or 5),
            token=args.get("connector_token"),
        )
        return {"vouchers": vouchers, "count": len(vouchers)}

    # 1. Sales Invoice (Item Based)
    elif tool_name == "create_sales_invoice_command":
        total_amt = float(args.get("total_amount") or 0.0)
        party = args.get("party_ledger") or "Customer Ledger"
        v_items = args.get("items") or [{"name": f"Sales - {party}", "itemName": f"Sales - {party}", "quantity": 1, "rate": total_amt, "amount": total_amt}]
        return await command_queue_service.create_sales_invoice(
            company_name=args.get("company_name") or "Default",
            party_ledger=party,
            date=args.get("date") or today_date,
            items=v_items,
            total_amount=total_amt,
            sales_ledger=args.get("sales_ledger") or "Sales",
            voucher_number=args.get("voucher_number"),
            narration=args.get("narration") or f"Sales Invoice - {party}",
            gst_rate=float(args.get("gst_rate", 18.0)),
            is_igst=bool(args.get("is_igst", False)),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
            tally_port=args.get("tally_port"),
        )

    # 2. Service Sales Invoice
    elif tool_name == "create_service_invoice_command":
        amt = float(args.get("amount") or 0.0)
        party = args.get("party_ledger") or "Customer Ledger"
        return await command_queue_service.create_service_invoice(
            company_name=args.get("company_name") or "Default",
            party_ledger=party,
            date=args.get("date") or today_date,
            amount=amt,
            service_income_ledger=args.get("service_income_ledger") or "Consultancy Income",
            voucher_number=args.get("voucher_number"),
            narration=args.get("narration") or f"Service Invoice - {party}",
            gst_rate=float(args.get("gst_rate", 18.0)),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
            tally_port=args.get("tally_port"),
        )

    # 3. Receipt Voucher
    elif tool_name == "create_receipt_voucher_command":
        return await command_queue_service.create_receipt(
            company_name=args.get("company_name") or "Default",
            party_ledger=args.get("party_ledger") or "Customer Ledger",
            bank_ledger=args.get("bank_or_cash_ledger") or args.get("bank_ledger") or "Bank Account",
            amount=float(args.get("amount") or 0.0),
            date=args.get("date") or today_date,
            voucher_number=args.get("voucher_number") or args.get("reference_no"),
            narration=args.get("narration"),
            payment_mode=args.get("payment_mode") or "NEFT",
            cheque_number=args.get("cheque_number"),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
            tally_port=args.get("tally_port"),
        )

    # 4. Payment Voucher
    elif tool_name == "create_payment_voucher_command":
        return await command_queue_service.create_payment(
            company_name=args.get("company_name") or "Default",
            party_ledger=args.get("party_ledger") or "Vendor Ledger",
            bank_ledger=args.get("bank_or_cash_ledger") or args.get("bank_ledger") or "Bank Account",
            amount=float(args.get("amount") or 0.0),
            date=args.get("date") or today_date,
            voucher_number=args.get("voucher_number"),
            narration=args.get("narration"),
            payment_mode=args.get("payment_mode") or "Cheque",
            cheque_number=args.get("cheque_number"),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
            tally_port=args.get("tally_port"),
        )

    # 5. Purchase Invoice
    elif tool_name == "create_purchase_invoice_command":
        total_amt = float(args.get("total_amount") or 0.0)
        party = args.get("party_ledger") or "Supplier Ledger"
        v_items = args.get("items") or [{"itemName": f"Material from {party}", "quantity": 1, "rate": total_amt, "amount": total_amt}]
        return await command_queue_service.create_purchase_invoice(
            company_name=args.get("company_name") or "Default",
            party_ledger=party,
            date=args.get("date") or today_date,
            items=v_items,
            total_amount=total_amt,
            purchase_ledger=args.get("purchase_ledger") or "Purchase",
            supplier_invoice_no=args.get("supplier_invoice_no"),
            narration=args.get("narration"),
            gst_rate=float(args.get("gst_rate", 18.0)),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
            tally_port=args.get("tally_port"),
        )

    # 6. Credit Note
    elif tool_name == "create_credit_note_command":
        return await command_queue_service.create_credit_note(
            company_name=args.get("company_name") or "Default",
            party_ledger=args.get("party_ledger") or "Customer Ledger",
            date=args.get("date") or today_date,
            amount=float(args.get("amount") or 0.0),
            original_invoice_no=args.get("original_invoice_no"),
            reason=args.get("reason") or "Damaged Goods",
            narration=args.get("narration"),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
            tally_port=args.get("tally_port"),
        )

    # 7. Debit Note
    elif tool_name == "create_debit_note_command":
        return await command_queue_service.create_debit_note(
            company_name=args.get("company_name") or "Default",
            party_ledger=args.get("party_ledger") or "Supplier Ledger",
            date=args.get("date") or today_date,
            amount=float(args.get("amount") or 0.0),
            original_invoice_no=args.get("original_invoice_no"),
            reason=args.get("reason") or "Defective Material",
            narration=args.get("narration"),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
            tally_port=args.get("tally_port"),
        )

    # 8. Journal
    elif tool_name == "create_journal_command":
        amt = float(args.get("amount") or 0.0)
        entries = args.get("ledger_entries") or [
            {"ledgerName": "General Expense", "amount": amt, "isDebit": True},
            {"ledgerName": "Cash", "amount": amt, "isDebit": False},
        ]
        return await command_queue_service.create_journal(
            company_name=args.get("company_name") or "Default",
            date=args.get("date") or today_date,
            amount=amt,
            narration=args.get("narration") or "Journal Entry",
            ledger_entries=entries,
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
            tally_port=args.get("tally_port"),
        )

    # 9. Contra
    elif tool_name == "create_contra_command":
        return await command_queue_service.create_contra(
            company_name=args.get("company_name") or "Default",
            date=args.get("date") or today_date,
            from_account=args.get("from_account") or "Cash",
            to_account=args.get("to_account") or "Bank Account",
            amount=float(args.get("amount") or 0.0),
            transaction_type=args.get("transaction_type") or "Deposit",
            narration=args.get("narration"),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
            tally_port=args.get("tally_port"),
        )

    # 10. Sales Order
    elif tool_name == "create_sales_order_command":
        total_amt = float(args.get("total_amount") or 0.0)
        party = args.get("party_ledger") or "Customer Ledger"
        v_items = args.get("items") or [{"itemName": f"Order Item for {party}", "quantity": 1, "rate": total_amt, "amount": total_amt}]
        return await command_queue_service.create_sales_order(
            company_name=args.get("company_name") or "Default",
            party_ledger=party,
            date=args.get("date") or today_date,
            items=v_items,
            total_amount=total_amt,
            order_no=args.get("order_no"),
            due_date=args.get("due_date"),
            narration=args.get("narration"),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
        )

    # 11. Purchase Order
    elif tool_name == "create_purchase_order_command":
        total_amt = float(args.get("total_amount") or 0.0)
        party = args.get("party_ledger") or "Supplier Ledger"
        v_items = args.get("items") or [{"itemName": f"PO Item for {party}", "quantity": 1, "rate": total_amt, "amount": total_amt}]
        return await command_queue_service.create_purchase_order(
            company_name=args.get("company_name") or "Default",
            party_ledger=party,
            date=args.get("date") or today_date,
            items=v_items,
            total_amount=total_amt,
            order_no=args.get("order_no"),
            due_date=args.get("due_date"),
            narration=args.get("narration"),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
        )

    # 12. Create Customer Master
    elif tool_name == "create_customer_command":
        return await command_queue_service.create_customer(
            company_name=args.get("company_name") or "Default",
            name=args.get("name") or "New Customer",
            gstin=args.get("gstin"),
            state=args.get("state"),
            phone=args.get("phone"),
            email=args.get("email"),
            address=args.get("address"),
            credit_days=int(args.get("credit_days", 30)),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
        )

    # 13. Create Supplier Master
    elif tool_name == "create_supplier_command":
        return await command_queue_service.create_supplier(
            company_name=args.get("company_name") or "Default",
            name=args.get("name") or "New Supplier",
            gstin=args.get("gstin"),
            state=args.get("state"),
            phone=args.get("phone"),
            email=args.get("email"),
            address=args.get("address"),
            credit_days=int(args.get("credit_days", 45)),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
        )

    # 14. Create Stock Item Master
    elif tool_name == "create_stock_item_command":
        return await command_queue_service.create_stock_item(
            company_name=args.get("company_name") or "Default",
            name=args.get("name") or "New Stock Item",
            units=args.get("units") or "NOS",
            hsn_code=args.get("hsn_code") or "",
            gst_rate=float(args.get("gst_rate", 18.0)),
            opening_qty=float(args.get("opening_qty", 0.0)),
            opening_rate=float(args.get("opening_rate", 0.0)),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
        )

    # 15. Create Unit Master
    elif tool_name == "create_unit_command":
        return await command_queue_service.create_unit(
            company_name=args.get("company_name") or "Default",
            symbol=args.get("symbol") or "NOS",
            formal_name=args.get("formal_name") or "Numbers",
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
        )

    # 16. Delete Voucher
    elif tool_name == "delete_voucher_command":
        return await command_queue_service.delete_voucher(
            company_name=args.get("company_name") or "Default",
            voucher_type=args.get("voucher_type") or "Sales",
            voucher_number=args.get("voucher_number") or "",
            date=args.get("date") or today_date,
            reason=args.get("reason") or "Cancelled by user on web",
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
        )

    # Legacy alias
    elif tool_name == "create_ledger_master_command":
        return await command_queue_service.create_party_master(
            company_name=args.get("company_name") or "Default",
            party_name=args.get("party_name") or "New Party",
            parent=args.get("parent") or "Sundry Debtors",
            gstin=args.get("gstin"),
            state=args.get("state"),
            mobile=args.get("mobile"),
            company_id=args.get("company_id"),
            connector_token=args.get("connector_token"),
        )

    # 18. Sales & Financial Module Analytics
    elif tool_name == "get_sales_analytics_command":
        return await connector_client.get_company_sales_module(
            endpoint_suffix=args.get("module", "sales"),
            company_name=args.get("company_name"),
            company_id=args.get("company_id"),
            q=args.get("q"),
            from_date=args.get("from_date"),
            to_date=args.get("to_date"),
            page=int(args.get("page", 1)),
            limit=int(args.get("limit", 20)),
            token=args.get("connector_token"),
        )

    # 18b. Outgoing Payments & Vendor Dues Module
    elif tool_name == "get_payments_command":
        return await connector_client.get_company_payments(
            company_name=args.get("company_name"),
            company_id=args.get("company_id"),
            q=args.get("q"),
            from_date=args.get("from_date") or args.get("from"),
            to_date=args.get("to_date") or args.get("to"),
            page=int(args.get("page", 1)),
            limit=int(args.get("limit", 10)),
            token=args.get("connector_token"),
        )

    # 19. Official Accounting Reports (Day Book, Trial Balance, P&L, Balance Sheet, Voucher Lines)
    elif tool_name == "get_accounting_report_command":
        report_type = args.get("report_type", "day-book")
        if report_type == "trial-balance":
            return await connector_client.get_company_trial_balance(
                company_name=args.get("company_name"),
                company_id=args.get("company_id"),
                page=int(args.get("page", 1)),
                limit=int(args.get("limit", 50)),
                q=args.get("q"),
                group=args.get("group"),
                token=args.get("connector_token"),
            )
        elif report_type == "pnl":
            return await connector_client.get_company_pnl(
                company_name=args.get("company_name"),
                company_id=args.get("company_id"),
                page=int(args.get("page", 1)),
                limit=int(args.get("limit", 50)),
                q=args.get("q"),
                ledger_type=args.get("ledger_type"),
                token=args.get("connector_token"),
            )
        elif report_type == "balance-sheet":
            return await connector_client.get_company_balance_sheet(
                company_name=args.get("company_name"),
                company_id=args.get("company_id"),
                page=int(args.get("page", 1)),
                limit=int(args.get("limit", 50)),
                q=args.get("q"),
                ledger_type=args.get("ledger_type"),
                token=args.get("connector_token"),
            )
        elif report_type == "voucher-lines":
            return await connector_client.get_company_voucher_lines(
                voucher_id=str(args.get("voucher_id", "VCH-001")),
                company_name=args.get("company_name"),
                company_id=args.get("company_id"),
                page=int(args.get("page", 1)),
                limit=int(args.get("limit", 100)),
                token=args.get("connector_token"),
            )
        else:
            return await connector_client.get_company_day_book(
                company_name=args.get("company_name"),
                company_id=args.get("company_id"),
                from_date=args.get("from_date"),
                to_date=args.get("to_date"),
                page=int(args.get("page", 1)),
                limit=int(args.get("limit", 50)),
                q=args.get("q"),
                token=args.get("connector_token"),
            )

    # 20. Cash & Bank Module (Cash in hand, Bank accounts, Liquid Funds)
    elif tool_name == "get_cash_bank_command":
        acc_type = str(args.get("account_type", "both")).lower()
        comp_name = args.get("company_name")
        comp_id = args.get("company_id")
        q = args.get("q")
        page = int(args.get("page", 1))
        limit = int(args.get("limit", 10))
        token = args.get("connector_token")

        cash_res = None
        bank_res = None

        if acc_type in ["cash", "both", "all"]:
            cash_res = await connector_client.get_company_cash(
                company_name=comp_name, company_id=comp_id, page=page, limit=limit, q=q if acc_type == "cash" else None, token=token
            )
        if acc_type in ["bank", "both", "all"]:
            bank_res = await connector_client.get_company_bank(
                company_name=comp_name, company_id=comp_id, page=page, limit=limit, q=q, token=token
            )

        cash_items = (cash_res.get("items") or []) if cash_res else []
        bank_items = (bank_res.get("items") or []) if bank_res else []
        total_cash = cash_res.get("total_amount", 0.0) if cash_res else 0.0
        total_bank = bank_res.get("total_amount", 0.0) if bank_res else 0.0

        resolved_comp = (
            (cash_res.get("company_name") if cash_res else None)
            or (bank_res.get("company_name") if bank_res else None)
            or comp_name
            or "Default"
        )
        resolved_cid = (
            (cash_res.get("company_id") if cash_res else None)
            or (bank_res.get("company_id") if bank_res else None)
            or comp_id
            or ""
        )

        return {
            "success": True,
            "module": acc_type,
            "company_name": resolved_comp,
            "company_id": resolved_cid,
            "search_query": q,
            "cash_accounts": cash_items,
            "bank_accounts": bank_items,
            "total_cash": round(total_cash, 2),
            "total_bank": round(total_bank, 2),
            "total_liquid": round(total_cash + total_bank, 2),
            "page": page,
            "limit": limit,
        }

    # 21. Live Parties & Customer/Supplier Module
    elif tool_name == "get_parties_command":
        comp_name = args.get("company_name")
        comp_id = args.get("company_id")
        q = args.get("q")
        page = int(args.get("page", 1))
        limit = int(args.get("limit", 50))
        token = args.get("connector_token")

        return await connector_client.get_company_parties(
            company_name=comp_name,
            company_id=comp_id,
            page=page,
            limit=limit,
            q=q,
            token=token,
        )

    else:
        return {"error": f"Tool '{tool_name}' is not recognized or permitted."}
