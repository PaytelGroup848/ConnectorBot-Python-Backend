import hashlib
import json
import logging
import datetime
from typing import Dict, Any, Optional, List
from app.modules.connector.client import connector_client

logger = logging.getLogger("connector_ai.commands")


class CommandQueueService:
    """
    Manages 2-way asynchronous command queuing to Tally Prime via CtrlBooks engine.
    Supports all 16 standardized CtrlBooks command envelope schemas.
    """
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

    # =========================================================================
    # 1. SALES INVOICE (ITEM / INVENTORY BASED) -> "CREATE_VOUCHER"
    # =========================================================================
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

    # =========================================================================
    # 2. SALES INVOICE (ACCOUNTING / SERVICE ONLY) -> "CREATE_VOUCHER"
    # =========================================================================
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

    # =========================================================================
    # 3. RECEIPT VOUCHER (CUSTOMER PAYMENT RECEIVED) -> "CREATE_RECEIPT"
    # =========================================================================
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

    # =========================================================================
    # 4. PAYMENT VOUCHER (VENDOR PAYMENT / EXPENSE) -> "CREATE_PAYMENT"
    # =========================================================================
    async def create_payment(
        self,
        company_name: str,
        party_ledger: str,
        bank_ledger: str,
        amount: float,
        date: str,
        voucher_number: Optional[str] = None,
        narration: Optional[str] = None,
        payment_mode: str = "Cheque",
        cheque_number: Optional[str] = None,
        cheque_date: Optional[str] = None,
        bill_allocations: Optional[List[Dict[str, Any]]] = None,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
        tally_port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Creates & syncs a Payment Voucher in CtrlBooks & Tally Prime."""
        cmd_id = voucher_number or f"PAY-{date}-{party_ledger[:4].upper()}"
        cmd_hash = self._generate_command_hash(company_name, "Payment", cmd_id)

        if cmd_hash in self._idempotency_cache:
            return self._idempotency_cache[cmd_hash]

        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        allocs = bill_allocations or [{"billType": "On Account", "billNumber": cmd_id, "amount": amount}]
        narr = narration or f"Payment made to {party_ledger} via {payment_mode}"

        ctrlbooks_api_body = {
            "type": "CREATE_PAYMENT",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "voucherType": "Payment",
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

        ctrlbooks_sync = await connector_client.push_voucher_command(
            company_id=resolved_company_id,
            command_payload=ctrlbooks_api_body,
            token=connector_token,
        )

        result = {
            "success": True,
            "status": "SYNCED_TO_CTRLBOOKS" if ctrlbooks_sync.get("pushed_to_ctrlbooks") else "QUEUED",
            "command_type": "CREATE_PAYMENT",
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

    # =========================================================================
    # 5. PURCHASE INVOICE (INWARD GOODS) -> "CREATE_PURCHASE"
    # =========================================================================
    async def create_purchase_invoice(
        self,
        company_name: str,
        party_ledger: str,
        date: str,
        items: list,
        total_amount: float,
        purchase_ledger: str = "Purchase",
        voucher_number: Optional[str] = None,
        supplier_invoice_no: Optional[str] = None,
        supplier_invoice_date: Optional[str] = None,
        narration: Optional[str] = None,
        gst_rate: float = 18.0,
        is_igst: bool = False,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
        tally_port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Creates & syncs a Purchase Invoice with input tax credit ledgers."""
        cmd_id = voucher_number or f"PUR-{date}-{party_ledger[:4].upper()}"
        cmd_hash = self._generate_command_hash(company_name, "Purchase", cmd_id)

        if cmd_hash in self._idempotency_cache:
            return self._idempotency_cache[cmd_hash]

        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        subtotal = round(sum(float(it.get("amount", 0.0)) for it in items) or total_amount, 2)
        rate_pct = float(gst_rate if gst_rate is not None else 18.0)

        ledgers = []
        if rate_pct <= 0:
            gst_total = 0.0
        elif is_igst:
            gst_total = round(subtotal * (rate_pct / 100.0), 2)
            ledgers.append({"ledgerName": "Input IGST", "amount": gst_total, "rate": rate_pct})
        else:
            half = rate_pct / 2.0
            cgst = round(subtotal * (half / 100.0), 2)
            sgst = round(subtotal * (half / 100.0), 2)
            ledgers.append({"ledgerName": "Input CGST", "amount": cgst, "rate": half})
            ledgers.append({"ledgerName": "Input SGST", "amount": sgst, "rate": half})
            gst_total = round(cgst + sgst, 2)

        grand_total = round(subtotal + gst_total, 2)
        narr = narration or f"Purchase received from {party_ledger}"

        normalized_items = []
        for idx, it in enumerate(items):
            normalized_items.append({
                "itemName": it.get("itemName") or it.get("name") or f"Stock Item {idx + 1}",
                "quantity": float(it.get("quantity", 1)),
                "rate": float(it.get("rate", subtotal)),
                "units": str(it.get("units") or it.get("unit") or "NOS").upper(),
                "discount": float(it.get("discount", 0.0)),
                "amount": float(it.get("amount", round(float(it.get("quantity", 1)) * float(it.get("rate", subtotal)), 2))),
                "hsnCode": str(it.get("hsnCode") or it.get("hsn_code") or "7214"),
                "godown": str(it.get("godown") or "Main Location"),
                "batch": str(it.get("batch") or "Primary Batch"),
            })

        ctrlbooks_api_body = {
            "type": "CREATE_PURCHASE",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "voucherType": "Purchase",
                "voucherNumber": cmd_id,
                "date": date,
                "partyLedger": party_ledger,
                "purchaseLedger": purchase_ledger,
                "amount": grand_total,
                "subTotal": subtotal,
                "taxes": gst_total,
                "narration": narr,
                "supplierInvoiceNo": supplier_invoice_no or cmd_id,
                "supplierInvoiceDate": supplier_invoice_date or date,
                "items": normalized_items,
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
            "command_type": "CREATE_PURCHASE",
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

    # =========================================================================
    # 6. CREDIT NOTE (SALES RETURN / REBATE) -> "CREATE_CREDIT_NOTE"
    # =========================================================================
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

    # =========================================================================
    # 7. DEBIT NOTE (PURCHASE RETURN / SHORTAGE) -> "CREATE_DEBIT_NOTE"
    # =========================================================================
    async def create_debit_note(
        self,
        company_name: str,
        party_ledger: str,
        date: str,
        amount: float,
        items: Optional[list] = None,
        debit_note_ledger: str = "Purchase Return",
        voucher_number: Optional[str] = None,
        original_invoice_no: Optional[str] = None,
        original_invoice_date: Optional[str] = None,
        reason: str = "Defective Material",
        narration: Optional[str] = None,
        gst_rate: float = 18.0,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
        tally_port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Creates & syncs a Debit Note voucher against a previous supplier purchase bill."""
        cmd_id = voucher_number or f"DN-{date}-{party_ledger[:4].upper()}"
        cmd_hash = self._generate_command_hash(company_name, "DebitNote", cmd_id)

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
            {"ledgerName": "Input CGST", "amount": half_t, "rate": half},
            {"ledgerName": "Input SGST", "amount": round(tax_part - half_t, 2), "rate": half},
        ] if gst_rate > 0 else []

        narr = narration or f"Debit note issued to {party_ledger} ({reason})"

        ctrlbooks_api_body = {
            "type": "CREATE_DEBIT_NOTE",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "voucherType": "Debit Note",
                "voucherNumber": cmd_id,
                "date": date,
                "partyLedger": party_ledger,
                "debitNoteLedger": debit_note_ledger,
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
            "command_type": "CREATE_DEBIT_NOTE",
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

    # =========================================================================
    # 8. JOURNAL VOUCHER (ADJUSTMENTS / PROVISIONS) -> "CREATE_JOURNAL"
    # =========================================================================
    async def create_journal(
        self,
        company_name: str,
        date: str,
        amount: float,
        narration: str,
        ledger_entries: List[Dict[str, Any]],
        voucher_number: Optional[str] = None,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
        tally_port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Creates & syncs a General Journal entry."""
        cmd_id = voucher_number or f"JRN-{date}-{str(int(amount))}"
        cmd_hash = self._generate_command_hash(company_name, "Journal", cmd_id)

        if cmd_hash in self._idempotency_cache:
            return self._idempotency_cache[cmd_hash]

        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        ctrlbooks_api_body = {
            "type": "CREATE_JOURNAL",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "voucherType": "Journal",
                "voucherNumber": cmd_id,
                "date": date,
                "narration": narration,
                "amount": amount,
                "ledgerEntries": ledger_entries,
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
            "command_type": "CREATE_JOURNAL",
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

    # =========================================================================
    # 9. CONTRA VOUCHER (BANK-TO-CASH / CASH-TO-BANK) -> "CREATE_CONTRA"
    # =========================================================================
    async def create_contra(
        self,
        company_name: str,
        date: str,
        from_account: str,
        to_account: str,
        amount: float,
        voucher_number: Optional[str] = None,
        narration: Optional[str] = None,
        transaction_type: str = "Deposit",
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
        tally_port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Creates & syncs a Contra Voucher (Cash/Bank transfer)."""
        cmd_id = voucher_number or f"CNT-{date}-{str(int(amount))}"
        cmd_hash = self._generate_command_hash(company_name, "Contra", cmd_id)

        if cmd_hash in self._idempotency_cache:
            return self._idempotency_cache[cmd_hash]

        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        narr = narration or f"{transaction_type} from {from_account} to {to_account}"

        ctrlbooks_api_body = {
            "type": "CREATE_CONTRA",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "voucherType": "Contra",
                "voucherNumber": cmd_id,
                "date": date,
                "fromAccount": from_account,
                "toAccount": to_account,
                "amount": amount,
                "narration": narr,
                "transactionType": transaction_type,
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
            "command_type": "CREATE_CONTRA",
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

    # =========================================================================
    # 10. SALES ORDER -> "CREATE_SALES_ORDER"
    # =========================================================================
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

    # =========================================================================
    # 11. PURCHASE ORDER -> "CREATE_PURCHASE_ORDER"
    # =========================================================================
    async def create_purchase_order(
        self,
        company_name: str,
        party_ledger: str,
        date: str,
        items: list,
        total_amount: float,
        purchase_ledger: str = "Purchase",
        order_no: Optional[str] = None,
        due_date: Optional[str] = None,
        voucher_number: Optional[str] = None,
        narration: Optional[str] = None,
        gst_rate: float = 18.0,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates & syncs a Vendor Purchase Order in Tally."""
        cmd_id = voucher_number or f"PO-{date}-{party_ledger[:4].upper()}"
        cmd_hash = self._generate_command_hash(company_name, "PurchaseOrder", cmd_id)

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
            {"ledgerName": "Input CGST", "amount": half_t, "rate": half},
            {"ledgerName": "Input SGST", "amount": round(tax_part - half_t, 2), "rate": half},
        ] if gst_rate > 0 else []

        grand_total = round(total_amount + tax_part, 2)

        ctrlbooks_api_body = {
            "type": "CREATE_PURCHASE_ORDER",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "voucherType": "Purchase Order",
                "voucherNumber": cmd_id,
                "date": date,
                "partyLedger": party_ledger,
                "purchaseLedger": purchase_ledger,
                "amount": grand_total,
                "narration": narration or f"Purchase Order {order_no or cmd_id}",
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
            "command_type": "CREATE_PURCHASE_ORDER",
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

    # =========================================================================
    # 12. CREATE CUSTOMER (PARTY MASTER) -> "CREATE_CUSTOMER"
    # =========================================================================
    async def create_customer(
        self,
        company_name: str,
        name: str,
        group: str = "Sundry Debtors",
        opening_balance: float = 0.0,
        bill_by_bill: bool = True,
        credit_days: int = 30,
        credit_limit: float = 500000.0,
        gstin: Optional[str] = None,
        state: Optional[str] = None,
        pan: Optional[str] = None,
        contact_person: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        address: Optional[str] = None,
        city: Optional[str] = None,
        pincode: Optional[str] = None,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a new Customer ledger master in CtrlBooks & Tally."""
        cmd_hash = self._generate_command_hash(company_name, "Customer", name)
        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        state_name = state or "Delhi"
        state_code = gstin[:2] if (gstin and len(gstin) >= 2) else "07"
        pan_num = pan or (gstin[2:12] if (gstin and len(gstin) >= 12) else "")

        ctrlbooks_api_body = {
            "type": "CREATE_CUSTOMER",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "partyType": "CUSTOMER",
                "name": name,
                "group": group,
                "openingBalance": opening_balance,
                "billByBill": bill_by_bill,
                "creditDays": credit_days,
                "creditLimit": credit_limit,
                "gst": {
                    "gstin": gstin or "",
                    "registrationType": "Regular" if gstin else "Unregistered",
                    "pan": pan_num,
                    "state": state_name,
                    "stateCode": state_code,
                },
                "contact": {
                    "contactPerson": contact_person or name,
                    "phone": phone or "",
                    "email": email or "",
                },
                "address": {
                    "line1": address or "",
                    "line2": "",
                    "city": city or "",
                    "state": state_name,
                    "pincode": pincode or "",
                    "country": "India",
                },
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
            "command_type": "CREATE_CUSTOMER",
            "command_hash": cmd_hash,
            "party_name": name,
            "company": company_name,
            "company_id": resolved_company_id,
            "ctrlbooks_sync": ctrlbooks_sync,
            "payload": ctrlbooks_api_body,
        }
        self._idempotency_cache[cmd_hash] = result
        return result

    # =========================================================================
    # 13. CREATE SUPPLIER / VENDOR -> "CREATE_SUPPLIER"
    # =========================================================================
    async def create_supplier(
        self,
        company_name: str,
        name: str,
        group: str = "Sundry Creditors",
        opening_balance: float = 0.0,
        bill_by_bill: bool = True,
        credit_days: int = 45,
        gstin: Optional[str] = None,
        state: Optional[str] = None,
        pan: Optional[str] = None,
        contact_person: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        address: Optional[str] = None,
        city: Optional[str] = None,
        pincode: Optional[str] = None,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a new Supplier / Vendor ledger master in CtrlBooks & Tally."""
        cmd_hash = self._generate_command_hash(company_name, "Supplier", name)
        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        state_name = state or "Delhi"
        state_code = gstin[:2] if (gstin and len(gstin) >= 2) else "07"
        pan_num = pan or (gstin[2:12] if (gstin and len(gstin) >= 12) else "")

        ctrlbooks_api_body = {
            "type": "CREATE_SUPPLIER",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "partyType": "SUPPLIER",
                "name": name,
                "group": group,
                "openingBalance": opening_balance,
                "billByBill": bill_by_bill,
                "creditDays": credit_days,
                "gst": {
                    "gstin": gstin or "",
                    "registrationType": "Regular" if gstin else "Unregistered",
                    "pan": pan_num,
                    "state": state_name,
                    "stateCode": state_code,
                },
                "contact": {
                    "contactPerson": contact_person or name,
                    "phone": phone or "",
                    "email": email or "",
                },
                "address": {
                    "line1": address or "",
                    "line2": "",
                    "city": city or "",
                    "state": state_name,
                    "pincode": pincode or "",
                    "country": "India",
                },
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
            "command_type": "CREATE_SUPPLIER",
            "command_hash": cmd_hash,
            "party_name": name,
            "company": company_name,
            "company_id": resolved_company_id,
            "ctrlbooks_sync": ctrlbooks_sync,
            "payload": ctrlbooks_api_body,
        }
        self._idempotency_cache[cmd_hash] = result
        return result

    # Legacy wrapper for backward compatibility
    async def create_party_master(
        self,
        company_name: str,
        party_name: str,
        parent: str = "Sundry Debtors",
        gstin: Optional[str] = None,
        state: Optional[str] = None,
        mobile: Optional[str] = None,
        email: Optional[str] = None,
        address: Optional[str] = None,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Backward-compatible party creation method routing to create_customer or create_supplier."""
        if "creditor" in parent.lower() or "supplier" in parent.lower() or "vendor" in parent.lower():
            return await self.create_supplier(
                company_name=company_name,
                name=party_name,
                group=parent,
                gstin=gstin,
                state=state,
                phone=mobile,
                email=email,
                address=address,
                company_id=company_id,
                connector_token=connector_token,
            )
        return await self.create_customer(
            company_name=company_name,
            name=party_name,
            group=parent,
            gstin=gstin,
            state=state,
            phone=mobile,
            email=email,
            address=address,
            company_id=company_id,
            connector_token=connector_token,
        )

    # =========================================================================
    # 14. CREATE STOCK ITEM MASTER -> "CREATE_STOCK_ITEM"
    # =========================================================================
    async def create_stock_item(
        self,
        company_name: str,
        name: str,
        group: str = "Primary",
        units: str = "NOS",
        opening_qty: float = 0.0,
        opening_rate: float = 0.0,
        opening_godown: str = "Main Location",
        hsn_code: str = "",
        gst_rate: float = 18.0,
        taxability: str = "Taxable",
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a new Inventory Item Master in CtrlBooks & Tally."""
        cmd_hash = self._generate_command_hash(company_name, "StockItem", name)
        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        half_r = gst_rate / 2.0
        ctrlbooks_api_body = {
            "type": "CREATE_STOCK_ITEM",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "name": name,
                "group": group,
                "units": units.upper(),
                "openingBalance": {
                    "quantity": opening_qty,
                    "rate": opening_rate,
                    "amount": round(opening_qty * opening_rate, 2),
                    "godown": opening_godown,
                },
                "gst": {
                    "applicable": gst_rate > 0,
                    "hsnCode": hsn_code,
                    "taxability": taxability,
                    "gstRate": gst_rate,
                    "cgstRate": half_r,
                    "sgstRate": half_r,
                    "igstRate": gst_rate,
                },
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
            "command_type": "CREATE_STOCK_ITEM",
            "command_hash": cmd_hash,
            "item_name": name,
            "company": company_name,
            "company_id": resolved_company_id,
            "ctrlbooks_sync": ctrlbooks_sync,
            "payload": ctrlbooks_api_body,
        }
        self._idempotency_cache[cmd_hash] = result
        return result

    # =========================================================================
    # 15. CREATE UNIT OF MEASUREMENT -> "CREATE_UNIT"
    # =========================================================================
    async def create_unit(
        self,
        company_name: str,
        symbol: str,
        formal_name: str,
        uqc: Optional[str] = None,
        decimal_places: int = 0,
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a new Unit of Measurement (UOM) in CtrlBooks & Tally."""
        cmd_hash = self._generate_command_hash(company_name, "Unit", symbol)
        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        ctrlbooks_api_body = {
            "type": "CREATE_UNIT",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "symbol": symbol.upper(),
                "formalName": formal_name,
                "uqc": uqc or f"{symbol.upper()}-{formal_name.upper()}",
                "decimalPlaces": decimal_places,
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
            "command_type": "CREATE_UNIT",
            "command_hash": cmd_hash,
            "symbol": symbol.upper(),
            "company": company_name,
            "company_id": resolved_company_id,
            "ctrlbooks_sync": ctrlbooks_sync,
            "payload": ctrlbooks_api_body,
        }
        self._idempotency_cache[cmd_hash] = result
        return result

    # =========================================================================
    # 16. DELETE / CANCEL VOUCHER -> "DELETE_VOUCHER"
    # =========================================================================
    async def delete_voucher(
        self,
        company_name: str,
        voucher_type: str,
        voucher_number: str,
        date: str,
        reason: str = "Cancelled by user on web",
        company_id: Optional[str] = None,
        connector_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deletes/cancels a voucher in CtrlBooks & Tally Prime."""
        cmd_hash = self._generate_command_hash(company_name, "DeleteVoucher", f"{voucher_type}:{voucher_number}")
        resolved_company_id = await connector_client.resolve_company_id(
            company_name=company_name,
            company_id=company_id,
            token=connector_token,
        )

        ctrlbooks_api_body = {
            "type": "DELETE_VOUCHER",
            "companyId": resolved_company_id,
            "companyName": company_name,
            "payload": {
                "voucherType": voucher_type,
                "voucherNumber": voucher_number,
                "date": date,
                "reason": reason,
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
            "command_type": "DELETE_VOUCHER",
            "command_hash": cmd_hash,
            "voucher_number": voucher_number,
            "company": company_name,
            "company_id": resolved_company_id,
            "ctrlbooks_sync": ctrlbooks_sync,
            "payload": ctrlbooks_api_body,
        }
        self._idempotency_cache[cmd_hash] = result
        return result

    def list_queued_commands(self) -> list:
        """Returns all vouchers and commands currently waiting in the 2-way queue for Tally sync."""
        return list(self._idempotency_cache.values())


command_queue_service = CommandQueueService()
