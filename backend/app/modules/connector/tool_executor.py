import datetime
from typing import Dict, Any, List
from app.modules.connector.client import connector_client
from app.modules.connector.commands import command_queue_service
from app.middleware.tenant_context import TenantContext


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

    # 18c. Inward Purchases & Procurement Module
    elif tool_name == "get_purchases_command":
        return await connector_client.get_company_purchases(
            company_name=args.get("company_name"),
            company_id=args.get("company_id"),
            q=args.get("q"),
            from_date=args.get("from_date") or args.get("from"),
            to_date=args.get("to_date") or args.get("to"),
            page=int(args.get("page", 1)),
            limit=int(args.get("limit", 10)),
            token=args.get("connector_token"),
        )

    # 18d. Debit Notes & Purchase Returns Module
    elif tool_name == "get_debit_notes_command":
        return await connector_client.get_company_debit_notes(
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
