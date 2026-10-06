import logging
from typing import Optional, Dict, Any, List
from app.core.config import settings

logger = logging.getLogger("connector_ai.connector_client")


class FinancialClientMixin:
    """Financial modules: Sales, Credit Notes, Receipts, Sales Orders, Payments, Purchases, Debit Notes."""
    async def get_company_sales_module(
        self,
        endpoint_suffix: str,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        q: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves real-time synchronized records from CtrlBooks Cloud API:
        - GET /companies/{CompanyId}/sales
        - GET /companies/{CompanyId}/credit-notes
        - GET /companies/{CompanyId}/receipts
        - GET /companies/{CompanyId}/sales-orders
        - GET /companies/{CompanyId}/payments
        - GET /companies/{CompanyId}/purchases
        - GET /companies/{CompanyId}/debit-notes
        Supports search query 'q', date range 'from' & 'to', pagination, and resilient local queue fallback.
        """
        comp_details = await self.resolve_company_details(company_name=company_name, company_id=company_id, token=token)
        resolved_cid = comp_details["company_id"]
        effective_company = comp_details["company_name"]

        params: Dict[str, Any] = {
            "page": page,
            "limit": limit,
        }
        if q and str(q).strip():
            params["q"] = str(q).strip()
        if from_date and str(from_date).strip():
            params["from"] = str(from_date).strip()
        if to_date and str(to_date).strip():
            params["to"] = str(to_date).strip()

        path = f"/companies/{resolved_cid}/{endpoint_suffix}"
        res = await self._request("GET", path, token=token, params=params)

        def _safe_float(val, default=0.0) -> float:
            try:
                if isinstance(val, dict):
                    val = val.get("$numberDecimal") or val.get("value") or default
                if val is None or val == "":
                    return default
                return float(str(val).replace(",", "").strip())
            except Exception:
                return default

        raw_items = []
        raw_d: Any = None
        pagination_data: Dict[str, Any] = {}
        total_amount = 0.0

        if res.get("success") and res.get("data") is not None:
            raw_d = res.get("data")
            if isinstance(raw_d, list):
                raw_items = raw_d
            elif isinstance(raw_d, dict):
                for k in [
                    endpoint_suffix.replace("-", ""),
                    endpoint_suffix,
                    "purchases",
                    "purchase",
                    "debitNotes",
                    "debitnotes",
                    "debit-notes",
                    "payments",
                    "payment",
                    "sales",
                    "creditNotes",
                    "creditnotes",
                    "receipts",
                    "salesOrders",
                    "salesorders",
                    "items",
                    "vouchers",
                    "records",
                    "results",
                    "docs",
                    "rows",
                    "data",
                ]:
                    if isinstance(raw_d.get(k), list):
                        raw_items = raw_d[k]
                        break

                pagination_data = (
                    raw_d.get("pagination")
                    or raw_d.get("meta")
                    or res.get("pagination")
                    or res.get("meta")
                    or {}
                )
                if not isinstance(pagination_data, dict):
                    pagination_data = {}

                if "totalAmount" in pagination_data:
                    total_amount = _safe_float(pagination_data.get("totalAmount"))
                elif "total_amount" in pagination_data:
                    total_amount = _safe_float(pagination_data.get("total_amount"))
                elif "totalAmount" in raw_d:
                    total_amount = _safe_float(raw_d.get("totalAmount"))
                elif "total_amount" in raw_d:
                    total_amount = _safe_float(raw_d.get("total_amount"))

        clean_items = []
        calc_total = 0.0
        for it in raw_items:
            amt = _safe_float(
                it.get("amount")
                or it.get("total")
                or it.get("totalAmount")
                or it.get("grandTotal")
                or it.get("grossAmount")
                or 0.0
            )
            calc_total += amt
            v_num = str(
                it.get("voucherNumber")
                or it.get("voucher_number")
                or it.get("orderNumber")
                or it.get("invoiceNumber")
                or it.get("reference")
                or it.get("id")
                or it.get("_id")
                or "N/A"
            )
            party = str(
                it.get("partyLedger")
                or it.get("party_ledger")
                or it.get("partyName")
                or it.get("party")
                or "Customer"
            )
            date_val = str(it.get("date") or it.get("effectiveDate") or "")
            if "T" in date_val:
                date_val = date_val.split("T")[0]

            clean_items.append({
                "id": str(it.get("_id") or it.get("id") or ""),
                "voucher_number": v_num,
                "party_ledger": party,
                "amount": amt,
                "date": date_val,
                "narration": str(it.get("narration") or ""),
                "status": str(it.get("status") or "SYNCED"),
            })

        if total_amount <= 0.0:
            total_amount = calc_total

        total_count = int(
            pagination_data.get("total")
            or pagination_data.get("totalItems")
            or pagination_data.get("totalRecords")
            or pagination_data.get("count")
            or (raw_d.get("total") if isinstance(raw_d, dict) else None)
            or (raw_d.get("count") if isinstance(raw_d, dict) else None)
            or len(clean_items)
        )

        if not clean_items:
            try:
                from app.modules.connector.commands import command_queue_service
                q_type_map = {
                    "sales": ("CREATE_VOUCHER", "Sales"),
                    "credit-notes": ("CREATE_CREDIT_NOTE", "Credit Note"),
                    "receipts": ("CREATE_RECEIPT", "Receipt"),
                    "sales-orders": ("CREATE_SALES_ORDER", "Sales Order"),
                    "payments": ("CREATE_PAYMENT", "Payment"),
                    "purchases": ("CREATE_PURCHASE", "Purchase"),
                    "debit-notes": ("CREATE_DEBIT_NOTE", "Debit Note"),
                }
                match_cmd, match_vtype = q_type_map.get(endpoint_suffix, ("CREATE_VOUCHER", "Sales"))
                for q_cmd in reversed(command_queue_service.list_queued_commands()):
                    c_type = q_cmd.get("command_type")
                    p_load = q_cmd.get("payload", {}).get("payload", {})
                    v_type = p_load.get("voucher_type")
                    if c_type == match_cmd or v_type == match_vtype:
                        q_date = str(p_load.get("date") or "")
                        if from_date and q_date and q_date < from_date:
                            continue
                        if to_date and q_date and q_date > to_date:
                            continue
                        q_party = str(p_load.get("party_ledger") or "Customer")
                        q_amt = float(p_load.get("amount") or 0.0)
                        if q and q.lower() not in q_party.lower():
                            continue
                        clean_items.append({
                            "id": str(q_cmd.get("command_id") or ""),
                            "voucher_number": str(q_cmd.get("voucher_number") or "QUEUED"),
                            "party_ledger": q_party,
                            "amount": q_amt,
                            "date": q_date or datetime.date.today().isoformat(),
                            "narration": str(p_load.get("narration") or ""),
                            "status": q_cmd.get("status", "QUEUED"),
                        })
                        total_amount += q_amt
                total_count = len(clean_items)
            except Exception:
                pass

        return {
            "success": True,
            "module": endpoint_suffix,
            "module_label": {
                "sales": "Sales",
                "credit-notes": "Credit Note",
                "receipts": "Receipt",
                "sales-orders": "Sales Order",
                "payments": "Payment",
                "purchases": "Purchase",
                "debit-notes": "Debit Note",
            }.get(endpoint_suffix, "Sales"),
            "company_name": effective_company,
            "company_id": resolved_cid,
            "from_date": from_date,
            "to_date": to_date,
            "total_count": total_count,
            "total_amount": round(total_amount, 2),
            "items": clean_items[:limit],
            "pagination": pagination_data,
        }

    async def get_company_sales(self, **kwargs) -> Dict[str, Any]:
        return await self.get_company_sales_module("sales", **kwargs)

    async def get_company_credit_notes(self, **kwargs) -> Dict[str, Any]:
        return await self.get_company_sales_module("credit-notes", **kwargs)

    async def get_company_receipts(self, **kwargs) -> Dict[str, Any]:
        return await self.get_company_sales_module("receipts", **kwargs)

    async def get_company_sales_orders(self, **kwargs) -> Dict[str, Any]:
        return await self.get_company_sales_module("sales-orders", **kwargs)

    async def get_company_payments(self, **kwargs) -> Dict[str, Any]:
        return await self.get_company_sales_module("payments", **kwargs)

    async def get_company_purchases(self, **kwargs) -> Dict[str, Any]:
        return await self.get_company_sales_module("purchases", **kwargs)

    async def get_company_debit_notes(self, **kwargs) -> Dict[str, Any]:
        return await self.get_company_sales_module("debit-notes", **kwargs)

