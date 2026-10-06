import datetime
import logging
from typing import Dict, Any, Optional, List
from app.modules.connector.client import connector_client

logger = logging.getLogger("connector_ai.commands")


class PurchaseCommandMixin:
    """Purchase bills, payments, debit notes, journal, contra, and purchase orders."""
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

