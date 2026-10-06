import datetime
import logging
from typing import Dict, Any, Optional, List
from app.modules.connector.client import connector_client

logger = logging.getLogger("connector_ai.commands")


class SalesCommandMixin:
    """Sales invoices, service invoices, receipts, credit notes, and sales orders."""
    async def create_sales_invoice(
        self,
        company_name: str,
        party_ledger: str,
        date: str,
        items: list,
        total_amount: float,
        sales_ledger: str = "Sales",
        voucher_number: Optional[str] = None,
        narration: str = "AI Generated Sales Invoice",
        gst_rate: float = 18.0,
        is_igst: bool = False,
        reference_no: Optional[str] = None,
        reference_date: Optional[str] = None,
        order_no: Optional[str] = None,
        due_date: Optional[str] = None,
        advanced_settings: Optional[Dict[str, Any]] = None,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
        tally_port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Creates & syncs a standard item-based GST Sales Invoice in CtrlBooks & Tally Prime."""
        cmd_id = voucher_number or f"INV-{date}-{party_ledger[:4].upper()}"
        cmd_hash = self._generate_command_hash(company_name, "Sales", cmd_id)

        if cmd_hash in self._idempotency_cache:
            logger.info(f"Idempotency hit for sales invoice {cmd_id}")
            return self._idempotency_cache[cmd_hash]

        balanced_items = self.apply_penny_balancing(items, total_amount)

        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        v_types = await connector_client.get_voucher_types(resolved_company_id, token=connector_token)
        resolved_voucher_type = "Sales"
        for vt in v_types:
            v_name = str(vt.get("name") or vt.get("voucherType") or "")
            if "sales" in v_name.lower():
                resolved_voucher_type = v_name
                break

        godowns = await connector_client.get_godowns(resolved_company_id, token=connector_token)
        resolved_godown = str((godowns[0].get("name") if godowns else None) or "Main Location")

        subtotal = round(sum(float(it.get("amount", 0.0)) for it in balanced_items) or total_amount, 2)

        # Dynamic GST computation & ledgers list
        rate_pct = float(gst_rate if gst_rate is not None else 18.0)
        ledgers = []
        if rate_pct <= 0:
            gst_total = 0.0
            tax_label = "0% (Exempt / Nil Rated)"
        elif is_igst:
            gst_total = round(subtotal * (rate_pct / 100.0), 2)
            ledgers.append({"ledgerName": f"IGST", "amount": gst_total, "rate": rate_pct})
            tax_label = f"{rate_pct:g}% IGST"
        else:
            half_rate = rate_pct / 2.0
            cgst_amount = round(subtotal * (half_rate / 100.0), 2)
            sgst_amount = round(subtotal * (half_rate / 100.0), 2)
            ledgers.append({"ledgerName": "CGST", "amount": cgst_amount, "rate": half_rate})
            ledgers.append({"ledgerName": "SGST", "amount": sgst_amount, "rate": half_rate})
            gst_total = round(cgst_amount + sgst_amount, 2)
            tax_label = f"{half_rate:g}% CGST + {half_rate:g}% SGST"

        grand_total = round(subtotal + gst_total, 2)

        # Normalize items into exact CtrlBooks CREATE_VOUCHER item schema
        normalized_items = []
        for idx, it in enumerate(balanced_items):
            raw_name = it.get("itemName") or it.get("name") or f"Item {idx + 1}"
            qty = float(it.get("quantity", 1) or 1)
            rate = float(it.get("rate", subtotal) or subtotal)
            amt = float(it.get("amount", round(qty * rate, 2)))
            unit_str = str(it.get("units") or it.get("unit") or "NOS").upper()
            normalized_items.append({
                "itemName": raw_name,
                "name": raw_name,
                "quantity": qty,
                "rate": rate,
                "units": unit_str,
                "discount": float(it.get("discount", 0.0)),
                "amount": amt,
                "hsnCode": str(it.get("hsnCode") or it.get("hsn_code") or "8205"),
                "godown": str(it.get("godown") or resolved_godown),
                "batch": str(it.get("batch") or "Primary Batch"),
                "description": str(it.get("description") or narration),
                "taxInclusive": bool(it.get("taxInclusive", False)),
            })

        default_adv = {
            "placeOfSupply": "Delhi",
            "gstinUin": "",
            "address": "India",
            "consigneeName": party_ledger,
            "consigneeAddress": "India",
            "consigneeGstinUin": "",
            "consigneeState": "Delhi",
            "dispatchFrom": resolved_godown,
            "dispatchThrough": "Standard Transport",
            "dispatchDocNo": f"DC-{cmd_id}",
            "dispatchDate": date,
            "termsOfDelivery": "Standard",
        }
        if advanced_settings:
            default_adv.update(advanced_settings)

        # Official CtrlBooks CREATE_VOUCHER Envelope
        ctrlbooks_api_body = {
            "type": "CREATE_VOUCHER",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "voucherType": resolved_voucher_type,
                "voucherNumber": cmd_id,
                "date": date,
                "partyLedger": party_ledger,
                "salesLedger": sales_ledger,
                "amount": grand_total,
                "subTotal": subtotal,
                "taxes": gst_total,
                "narration": narration,
                "referenceNumber": reference_no or f"REF-{cmd_id}",
                "referenceDate": reference_date or date,
                "orderNo": order_no or f"ORD-{cmd_id}",
                "dueDate": due_date or date,
                "items": normalized_items,
                "ledgers": ledgers,
                "advancedSettings": default_adv,
            },
        }

        # Local Tally XML
        tally_xml = connector_client.build_tally_voucher_xml(
            company_name=company_name,
            voucher_type=resolved_voucher_type,
            voucher_number=cmd_id,
            date_str=date,
            party_ledger=party_ledger,
            narration=narration,
            total_amount=grand_total,
            taxable_amount=subtotal,
            ledger_entries=[{"ledger": l["ledgerName"], "amount": l["amount"]} for l in ledgers],
            sales_or_bank_ledger=sales_ledger,
        )

        ctrlbooks_sync = await connector_client.push_voucher_command(
            company_id=resolved_company_id,
            command_payload=ctrlbooks_api_body,
            token=connector_token,
        )
        local_tally_sync = await connector_client.push_direct_tally_xml(
            xml_payload=tally_xml,
            preferred_port=tally_port,
        )

        sync_status = (
            "SYNCED_TO_CTRLBOOKS"
            if ctrlbooks_sync.get("pushed_to_ctrlbooks")
            else ("SYNCED_TO_TALLY" if local_tally_sync.get("pushed_to_local_tally") else "QUEUED")
        )

        result = {
            "success": True,
            "status": sync_status,
            "command_type": "CREATE_VOUCHER",
            "command_hash": cmd_hash,
            "command_id": ctrlbooks_sync.get("ctrlbooks_command_id") or cmd_hash[:24],
            "voucher_number": cmd_id,
            "company": company_name,
            "company_id": resolved_company_id,
            "ctrlbooks_sync": ctrlbooks_sync,
            "local_tally_sync": local_tally_sync,
            "tally_xml": tally_xml,
            "payload": {
                **ctrlbooks_api_body,
                "payload": {
                    **ctrlbooks_api_body["payload"],
                    "voucher_type": "Sales",
                    "party_ledger": party_ledger,
                    "tax_label": tax_label,
                }
            },
        }
        self._idempotency_cache[cmd_hash] = result
        return result

    async def create_service_invoice(
        self,
        company_name: str,
        party_ledger: str,
        date: str,
        amount: float,
        service_income_ledger: str = "Consultancy Income",
        voucher_number: Optional[str] = None,
        narration: str = "Professional Consultancy Charges",
        gst_rate: float = 18.0,
        ledger_entries: Optional[List[Dict[str, Any]]] = None,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
        tally_port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Creates & syncs an Accounting/Service Sales Invoice without inventory items."""
        cmd_id = voucher_number or f"SRV-{date}-{party_ledger[:4].upper()}"
        cmd_hash = self._generate_command_hash(company_name, "ServiceSales", cmd_id)

        if cmd_hash in self._idempotency_cache:
            return self._idempotency_cache[cmd_hash]

        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        if not ledger_entries:
            tax_rate = float(gst_rate or 0.0)
            if tax_rate > 0:
                base_amt = round(amount / (1.0 + (tax_rate / 100.0)), 2)
                tax_amt = round(amount - base_amt, 2)
                half_tax = round(tax_amt / 2.0, 2)
                other_half = round(tax_amt - half_tax, 2)
                entries = [
                    {"ledgerName": service_income_ledger, "amount": base_amt, "isDebit": False},
                    {"ledgerName": "CGST", "amount": half_tax, "isDebit": False},
                    {"ledgerName": "SGST", "amount": other_half, "isDebit": False},
                    {"ledgerName": party_ledger, "amount": amount, "isDebit": True},
                ]
            else:
                entries = [
                    {"ledgerName": service_income_ledger, "amount": amount, "isDebit": False},
                    {"ledgerName": party_ledger, "amount": amount, "isDebit": True},
                ]
        else:
            entries = ledger_entries

        ctrlbooks_api_body = {
            "type": "CREATE_VOUCHER",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "voucherType": "Sales",
                "voucherNumber": cmd_id,
                "date": date,
                "partyLedger": party_ledger,
                "amount": amount,
                "narration": narration,
                "ledgerEntries": entries,
            },
        }

        ctrlbooks_sync = await connector_client.push_voucher_command(
            company_id=resolved_company_id,
            command_payload=ctrlbooks_api_body,
            token=connector_token,
        )

        result = {
            "success": True,
            "status": "SYNCED_TO_CTRLBOOKS" if ctrlbooks_sync.get("pushed_to_ctrlbooks") else "QUEUED",
            "command_type": "CREATE_VOUCHER",
            "command_hash": cmd_hash,
            "command_id": ctrlbooks_sync.get("ctrlbooks_command_id") or cmd_hash[:24],
            "voucher_number": cmd_id,
            "company": company_name,
            "company_id": resolved_company_id,
            "ctrlbooks_sync": ctrlbooks_sync,
            "payload": ctrlbooks_api_body,
        }
        self._idempotency_cache[cmd_hash] = result
        return result

    async def create_receipt(
        self,
        company_name: str,
        party_ledger: str,
        bank_ledger: str,
        amount: float,
        date: str,
        voucher_number: Optional[str] = None,
        narration: Optional[str] = None,
        payment_mode: str = "NEFT",
        cheque_number: Optional[str] = None,
        cheque_date: Optional[str] = None,
        bill_allocations: Optional[List[Dict[str, Any]]] = None,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
        tally_port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Creates & syncs a Receipt Voucher with bank details and bill allocations."""
        cmd_id = voucher_number or f"REC-{date}-{party_ledger[:4].upper()}"
        cmd_hash = self._generate_command_hash(company_name, "Receipt", cmd_id)

        if cmd_hash in self._idempotency_cache:
            return self._idempotency_cache[cmd_hash]

        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        allocs = bill_allocations or [{"billType": "On Account", "billNumber": cmd_id, "amount": amount}]
        narr = narration or f"Received from {party_ledger} via {payment_mode} (Ref #{cmd_id})"

        ctrlbooks_api_body = {
            "type": "CREATE_RECEIPT",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "voucherType": "Receipt",
                "voucherNumber": cmd_id,
                "date": date,
                "partyLedger": party_ledger,
                "bankLedger": bank_ledger,
                "amount": amount,
                "narration": narr,
                "paymentMode": payment_mode,
                "chequeNumber": cheque_number or "",
                "chequeDate": cheque_date or date,
                "billAllocations": allocs,
            },
        }

        tally_xml = connector_client.build_tally_voucher_xml(
            company_name=company_name,
            voucher_type="Receipt",
            voucher_number=cmd_id,
            date_str=date,
            party_ledger=party_ledger,
            narration=narr,
            total_amount=amount,
            taxable_amount=amount,
            ledger_entries=[],
            sales_or_bank_ledger=bank_ledger,
        )

        ctrlbooks_sync = await connector_client.push_voucher_command(
            company_id=resolved_company_id,
            command_payload=ctrlbooks_api_body,
            token=connector_token,
        )
        local_tally_sync = await connector_client.push_direct_tally_xml(
            xml_payload=tally_xml,
            preferred_port=tally_port,
        )

        result = {
            "success": True,
            "status": "SYNCED_TO_CTRLBOOKS" if ctrlbooks_sync.get("pushed_to_ctrlbooks") else "QUEUED",
            "command_type": "CREATE_RECEIPT",
            "command_hash": cmd_hash,
            "command_id": ctrlbooks_sync.get("ctrlbooks_command_id") or cmd_hash[:24],
            "voucher_number": cmd_id,
            "company": company_name,
            "company_id": resolved_company_id,
            "ctrlbooks_sync": ctrlbooks_sync,
            "local_tally_sync": local_tally_sync,
            "tally_xml": tally_xml,
            "payload": {
                **ctrlbooks_api_body,
                "payload": {
                    **ctrlbooks_api_body["payload"],
                    "voucher_type": "Receipt",
                    "party_ledger": party_ledger,
                    "bank_or_cash_ledger": bank_ledger,
                }
            },
        }
        self._idempotency_cache[cmd_hash] = result
        return result

    async def create_credit_note(
        self,
        company_name: str,
        party_ledger: str,
        date: str,
        amount: float,
        items: Optional[list] = None,
        credit_note_ledger: str = "Sales Return",
        voucher_number: Optional[str] = None,
        original_invoice_no: Optional[str] = None,
        original_invoice_date: Optional[str] = None,
        reason: str = "Damaged Goods",
        narration: Optional[str] = None,
        gst_rate: float = 18.0,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
        tally_port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Creates & syncs a Credit Note voucher against a previous sales invoice."""
        cmd_id = voucher_number or f"CN-{date}-{party_ledger[:4].upper()}"
        cmd_hash = self._generate_command_hash(company_name, "CreditNote", cmd_id)

        if cmd_hash in self._idempotency_cache:
            return self._idempotency_cache[cmd_hash]

        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        half = gst_rate / 2.0
        tax_part = round(amount * gst_rate / (100.0 + gst_rate), 2) if gst_rate > 0 else 0.0
        half_t = round(tax_part / 2.0, 2)
        ledgers = [
            {"ledgerName": "CGST", "amount": half_t, "rate": half},
            {"ledgerName": "SGST", "amount": round(tax_part - half_t, 2), "rate": half},
        ] if gst_rate > 0 else []

        narr = narration or f"Credit note issued to {party_ledger} ({reason})"

        ctrlbooks_api_body = {
            "type": "CREATE_CREDIT_NOTE",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "voucherType": "Credit Note",
                "voucherNumber": cmd_id,
                "date": date,
                "partyLedger": party_ledger,
                "creditNoteLedger": credit_note_ledger,
                "amount": amount,
                "narration": narr,
                "originalInvoiceNo": original_invoice_no or "",
                "originalInvoiceDate": original_invoice_date or date,
                "reason": reason,
                "items": items or [],
                "ledgers": ledgers,
            },
        }

        ctrlbooks_sync = await connector_client.push_voucher_command(
            company_id=resolved_company_id,
            command_payload=ctrlbooks_api_body,
            token=connector_token,
        )

        result = {
            "success": True,
            "status": "SYNCED_TO_CTRLBOOKS" if ctrlbooks_sync.get("pushed_to_ctrlbooks") else "QUEUED",
            "command_type": "CREATE_CREDIT_NOTE",
            "command_hash": cmd_hash,
            "command_id": ctrlbooks_sync.get("ctrlbooks_command_id") or cmd_hash[:24],
            "voucher_number": cmd_id,
            "company": company_name,
            "company_id": resolved_company_id,
            "ctrlbooks_sync": ctrlbooks_sync,
            "payload": ctrlbooks_api_body,
        }
        self._idempotency_cache[cmd_hash] = result
        return result

    async def create_sales_order(
        self,
        company_name: str,
        party_ledger: str,
        date: str,
        items: list,
        total_amount: float,
        sales_ledger: str = "Sales",
        order_no: Optional[str] = None,
        due_date: Optional[str] = None,
        voucher_number: Optional[str] = None,
        narration: Optional[str] = None,
        gst_rate: float = 18.0,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates & syncs a Customer Sales Order in Tally."""
        cmd_id = voucher_number or f"SO-{date}-{party_ledger[:4].upper()}"
        cmd_hash = self._generate_command_hash(company_name, "SalesOrder", cmd_id)

        if cmd_hash in self._idempotency_cache:
            return self._idempotency_cache[cmd_hash]

        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        half = gst_rate / 2.0
        tax_part = round(total_amount * (gst_rate / 100.0), 2)
        half_t = round(tax_part / 2.0, 2)
        ledgers = [
            {"ledgerName": "CGST", "amount": half_t, "rate": half},
            {"ledgerName": "SGST", "amount": round(tax_part - half_t, 2), "rate": half},
        ] if gst_rate > 0 else []

        grand_total = round(total_amount + tax_part, 2)

        ctrlbooks_api_body = {
            "type": "CREATE_SALES_ORDER",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "voucherType": "Sales Order",
                "voucherNumber": cmd_id,
                "date": date,
                "partyLedger": party_ledger,
                "salesLedger": sales_ledger,
                "amount": grand_total,
                "narration": narration or f"Sales order against customer PO {order_no or cmd_id}",
                "orderNo": order_no or cmd_id,
                "dueDate": due_date or date,
                "items": items,
                "ledgers": ledgers,
            },
        }

        ctrlbooks_sync = await connector_client.push_voucher_command(
            company_id=resolved_company_id,
            command_payload=ctrlbooks_api_body,
            token=connector_token,
        )

        result = {
            "success": True,
            "status": "SYNCED_TO_CTRLBOOKS" if ctrlbooks_sync.get("pushed_to_ctrlbooks") else "QUEUED",
            "command_type": "CREATE_SALES_ORDER",
            "command_hash": cmd_hash,
            "command_id": ctrlbooks_sync.get("ctrlbooks_command_id") or cmd_hash[:24],
            "voucher_number": cmd_id,
            "company": company_name,
            "company_id": resolved_company_id,
            "ctrlbooks_sync": ctrlbooks_sync,
            "payload": ctrlbooks_api_body,
        }
        self._idempotency_cache[cmd_hash] = result
        return result

