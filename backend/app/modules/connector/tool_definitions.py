from typing import List, Dict, Any

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
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
    {
        "type": "function",
        "function": {
            "name": "get_purchases_command",
            "description": "Retrieves real-time synchronized purchase bills, inward invoices, and supplier procurement records from Tally Prime via CtrlBooks Cloud API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "company_id": {"type": "string", "description": "Optional specific Company ID"},
                    "q": {"type": "string", "description": "Search query filter (supplier name, item, or bill number)"},
                    "from_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                    "to_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                    "page": {"type": "number", "description": "Page number (default: 1)"},
                    "limit": {"type": "number", "description": "Max records (default: 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_debit_notes_command",
            "description": "Retrieves real-time synchronized debit notes, purchase returns, and supplier adjustment vouchers from Tally Prime via CtrlBooks Cloud API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Name of the Tally company"},
                    "company_id": {"type": "string", "description": "Optional specific Company ID"},
                    "q": {"type": "string", "description": "Search query filter (supplier/vendor name or note number)"},
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
    {
        "type": "function",
        "function": {
            "name": "get_my_entries_command",
            "description": "Retrieves user's created entries from CtrlBooks My Entry queue. Filters by status (PENDING, SENT, DONE, FAILED), command type (CREATE_VOUCHER, CREATE_PARTY, CREATE_STOCK_ITEM), voucherType (Sales, Quotation, Receipt, Payment, Sales Order, Purchase, Journal, Contra, Purchase Order, Credit Note, Physical Stock, Receipt Note, Delivery Note), or keyword search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "Optional company name"},
                    "command_type": {"type": "string", "description": "CREATE_VOUCHER, CREATE_PARTY, or CREATE_STOCK_ITEM", "enum": ["CREATE_VOUCHER", "CREATE_PARTY", "CREATE_STOCK_ITEM"]},
                    "voucher_type": {"type": "string", "description": "Specific voucher type e.g. Quotation, Sales, Receipt, Payment, Sales Order, Purchase, Journal, Contra, Purchase Order, Credit Note, Physical Stock, Receipt Note, Delivery Note"},
                    "status": {"type": "string", "description": "Status filter e.g. PENDING, SENT, PENDING,SENT, DONE, FAILED"},
                    "q": {"type": "string", "description": "Search keyword by party name or voucher number"},
                    "page": {"type": "number", "description": "Page number (default: 1)"},
                    "limit": {"type": "number", "description": "Number of entries to return (default: 20)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_my_entry_command",
            "description": "Deletes or cancels a specific queued entry/command from CtrlBooks by Command ID (DELETE /companies/{CompanyId}/commands/{CommandId}).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command_id": {"type": "string", "description": "The exact Command ID to delete"},
                    "company_name": {"type": "string", "description": "Optional company name"},
                },
                "required": ["command_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_gstin_command",
            "description": "Verifies an Indian GST Number (GSTIN) against official Tally Solutions GST API. Returns verified Legal Name, Trade Name, Registration Type, Full Address, State, and Active Status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "gstin": {"type": "string", "description": "15-character GST Number to verify e.g. 24AAACC1206D1ZM"},
                },
                "required": ["gstin"],
            },
        },
    },
]
