import logging
from typing import Optional, Dict, Any, List
from app.core.config import settings

logger = logging.getLogger("connector_ai.connector_client")


class ReportsClientMixin:
    """Official accounting reports: Day Book, Trial Balance, Profit and Loss, Balance Sheet, Voucher Lines."""
    async def get_company_day_book(
        self,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
        q: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches real-time Day Book transactions from GET /companies/{CompanyId}/reports/day-book."""
        comp_details = await self.resolve_company_details(company_name=company_name, company_id=company_id, token=token)
        resolved_cid = comp_details["company_id"]
        effective_company = comp_details["company_name"]

        params: Dict[str, Any] = {"page": page, "limit": limit}
        if from_date:
            params["from"] = str(from_date).strip()
        if to_date:
            params["to"] = str(to_date).strip()
        if q and str(q).strip():
            params["q"] = str(q).strip()

        path = f"/companies/{resolved_cid}/reports/day-book"
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

        raw_rows = []
        pagination_data: Dict[str, Any] = {}
        if res.get("success") and res.get("data") is not None:
            raw_d = res.get("data")
            if isinstance(raw_d, list):
                raw_rows = raw_d
            elif isinstance(raw_d, dict):
                for k in ["dayBook", "day_book", "dayBookData", "entries", "vouchers", "items", "records", "results", "docs", "rows", "data"]:
                    if isinstance(raw_d.get(k), list):
                        raw_rows = raw_d[k]
                        break
                pagination_data = raw_d.get("pagination") or raw_d.get("meta") or {}

        clean_rows = []
        total_debit = 0.0
        total_credit = 0.0

        for it in raw_rows:
            nested_items = it.get("items") if isinstance(it.get("items"), list) and it.get("items") else []
            first_nested = nested_items[0] if nested_items and isinstance(nested_items[0], dict) else {}
            merged = {**it, **first_nested} if first_nested else it

            v_type = str(merged.get("voucherType") or merged.get("voucher_type") or merged.get("type") or "Voucher")
            v_num = str(merged.get("voucherNumber") or merged.get("voucher_number") or merged.get("id") or "N/A")
            party = str(merged.get("partyLedger") or merged.get("party_ledger") or merged.get("particulars") or merged.get("party") or "Party")
            date_val = str(merged.get("date") or it.get("date") or "")
            if "T" in date_val:
                date_val = date_val.split("T")[0]

            amt = _safe_float(merged.get("amount") or merged.get("total") or merged.get("totalAmount") or 0.0)
            debit = _safe_float(merged.get("debit") or (amt if v_type.lower() in ("payment", "purchase") else 0.0))
            credit = _safe_float(merged.get("credit") or (amt if v_type.lower() in ("receipt", "sales") else 0.0))

            total_debit += debit
            total_credit += credit

            clean_rows.append({
                "date": date_val,
                "voucher_type": v_type,
                "voucher_number": v_num,
                "party_ledger": party,
                "amount": amt,
                "debit": debit,
                "credit": credit,
                "narration": str(merged.get("narration") or ""),
            })

        # Resilient local fallback from command queue if upstream daybook returned empty
        if not clean_rows:
            try:
                from app.modules.connector.commands import command_queue_service
                for q_cmd in reversed(command_queue_service.list_queued_commands()):
                    p_load = q_cmd.get("payload", {}).get("payload", {})
                    q_date = str(p_load.get("date") or "")
                    if from_date and q_date and q_date < from_date:
                        continue
                    if to_date and q_date and q_date > to_date:
                        continue
                    v_type = str(p_load.get("voucher_type") or q_cmd.get("command_type", "Voucher"))
                    amt = float(p_load.get("amount") or 0.0)
                    party = str(p_load.get("party_ledger") or "Customer")
                    if v_type.lower() in ("receipt", "sales"):
                        total_credit += amt
                    else:
                        total_debit += amt
                    clean_rows.append({
                        "date": q_date or datetime.date.today().isoformat(),
                        "voucher_type": v_type,
                        "voucher_number": str(q_cmd.get("voucher_number") or "QUEUED"),
                        "party_ledger": party,
                        "amount": amt,
                        "debit": amt if v_type.lower() not in ("receipt", "sales") else 0.0,
                        "credit": amt if v_type.lower() in ("receipt", "sales") else 0.0,
                        "narration": str(p_load.get("narration") or ""),
                    })
            except Exception:
                pass

        return {
            "success": True,
            "report_type": "day-book",
            "report_title": "Day Book Report",
            "company_name": effective_company,
            "company_id": resolved_cid,
            "from_date": from_date,
            "to_date": to_date,
            "total_count": len(clean_rows),
            "total_debit": round(total_debit, 2),
            "total_credit": round(total_credit, 2),
            "net_amount": round(abs(total_credit - total_debit), 2),
            "rows": clean_rows[:limit],
            "pagination": pagination_data,
        }

    async def get_company_trial_balance(
        self,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
        q: Optional[str] = None,
        group: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches Trial Balance from GET /companies/{CompanyId}/reports/trial-balance."""
        comp_details = await self.resolve_company_details(company_name=company_name, company_id=company_id, token=token)
        resolved_cid = comp_details["company_id"]
        effective_company = comp_details["company_name"]

        params: Dict[str, Any] = {"page": page, "limit": limit}
        if q and str(q).strip():
            params["q"] = str(q).strip()
        if group and str(group).strip():
            params["group"] = str(group).strip()

        path = f"/companies/{resolved_cid}/reports/trial-balance"
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

        raw_rows = []
        pagination_data: Dict[str, Any] = {}
        if res.get("success") and res.get("data") is not None:
            raw_d = res.get("data")
            if isinstance(raw_d, list):
                raw_rows = raw_d
            elif isinstance(raw_d, dict):
                for k in ["trialBalance", "trial_balance", "trialBalanceData", "ledgers", "balances", "items", "records", "results", "rows", "data"]:
                    if isinstance(raw_d.get(k), list):
                        raw_rows = raw_d[k]
                        break
                pagination_data = raw_d.get("pagination") or raw_d.get("meta") or {}

        clean_rows = []
        tot_debit = 0.0
        tot_credit = 0.0

        for it in raw_rows:
            l_name = str(it.get("name") or it.get("ledgerName") or it.get("particulars") or "Ledger")
            p_group = str(it.get("parent") or it.get("group") or it.get("parentGroup") or "General")
            debit = _safe_float(it.get("debit") or it.get("closingDebit") or 0.0)
            credit = _safe_float(it.get("credit") or it.get("closingCredit") or 0.0)
            closing = _safe_float(it.get("closingBalance") or it.get("closing_balance") or it.get("balance") or (debit - credit))

            tot_debit += debit
            tot_credit += credit

            clean_rows.append({
                "ledger_name": l_name,
                "group": p_group,
                "debit": debit,
                "credit": credit,
                "closing_balance": closing,
            })

        return {
            "success": True,
            "report_type": "trial-balance",
            "report_title": f"Trial Balance {f'({group})' if group else ''}".strip(),
            "company_name": effective_company,
            "company_id": resolved_cid,
            "group": group,
            "total_count": len(clean_rows),
            "total_debit": round(tot_debit, 2),
            "total_credit": round(tot_credit, 2),
            "rows": clean_rows[:limit],
            "pagination": pagination_data,
        }

    async def get_company_pnl(
        self,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
        q: Optional[str] = None,
        ledger_type: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches Profit & Loss report from GET /companies/{CompanyId}/reports/pnl."""
        comp_details = await self.resolve_company_details(company_name=company_name, company_id=company_id, token=token)
        resolved_cid = comp_details["company_id"]
        effective_company = comp_details["company_name"]

        params: Dict[str, Any] = {"page": page, "limit": limit}
        if q and str(q).strip():
            params["q"] = str(q).strip()
        if ledger_type and str(ledger_type).strip():
            params["ledgerType"] = str(ledger_type).strip()

        path = f"/companies/{resolved_cid}/reports/pnl"
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

        raw_rows = []
        pagination_data: Dict[str, Any] = {}
        if res.get("success") and res.get("data") is not None:
            raw_d = res.get("data")
            if isinstance(raw_d, list):
                raw_rows = raw_d
            elif isinstance(raw_d, dict):
                for k in ["pnl", "profitLoss", "profit_loss", "accounts", "items", "records", "results", "rows", "data"]:
                    if isinstance(raw_d.get(k), list):
                        raw_rows = raw_d[k]
                        break
                pagination_data = raw_d.get("pagination") or raw_d.get("meta") or {}

        clean_rows = []
        total_income = 0.0
        total_expense = 0.0

        for it in raw_rows:
            p_name = str(it.get("particulars") or it.get("name") or it.get("ledgerName") or "Account")
            l_type = str(it.get("ledgerType") or it.get("type") or ("income" if "income" in p_name.lower() or "sales" in p_name.lower() else "expense"))
            amt = _safe_float(it.get("amount") or it.get("total") or 0.0)

            if l_type.lower() == "income":
                total_income += amt
            else:
                total_expense += amt

            clean_rows.append({
                "particulars": p_name,
                "ledger_type": l_type,
                "amount": amt,
            })

        net_profit = total_income - total_expense

        return {
            "success": True,
            "report_type": "pnl",
            "report_title": "Profit & Loss Report",
            "company_name": effective_company,
            "company_id": resolved_cid,
            "ledger_type": ledger_type,
            "total_count": len(clean_rows),
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "net_profit": round(net_profit, 2),
            "is_profit": net_profit >= 0,
            "rows": clean_rows[:limit],
            "pagination": pagination_data,
        }

    async def get_company_balance_sheet(
        self,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
        q: Optional[str] = None,
        ledger_type: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches Balance Sheet from GET /companies/{CompanyId}/reports/balance-sheet."""
        comp_details = await self.resolve_company_details(company_name=company_name, company_id=company_id, token=token)
        resolved_cid = comp_details["company_id"]
        effective_company = comp_details["company_name"]

        params: Dict[str, Any] = {"page": page, "limit": limit}
        if q and str(q).strip():
            params["q"] = str(q).strip()
        if ledger_type and str(ledger_type).strip():
            params["ledgerType"] = str(ledger_type).strip()

        path = f"/companies/{resolved_cid}/reports/balance-sheet"
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

        raw_rows = []
        pagination_data: Dict[str, Any] = {}
        if res.get("success") and res.get("data") is not None:
            raw_d = res.get("data")
            if isinstance(raw_d, list):
                raw_rows = raw_d
            elif isinstance(raw_d, dict):
                for k in ["balanceSheet", "balance_sheet", "accounts", "items", "records", "results", "rows", "data"]:
                    if isinstance(raw_d.get(k), list):
                        raw_rows = raw_d[k]
                        break
                pagination_data = raw_d.get("pagination") or raw_d.get("meta") or {}

        clean_rows = []
        total_assets = 0.0
        total_liabilities = 0.0

        for it in raw_rows:
            p_name = str(it.get("particulars") or it.get("name") or it.get("ledgerName") or "Account")
            l_type = str(it.get("ledgerType") or it.get("type") or ("asset" if "asset" in p_name.lower() or "bank" in p_name.lower() or "cash" in p_name.lower() else "liability"))
            amt = _safe_float(it.get("amount") or it.get("total") or 0.0)

            if l_type.lower() == "asset":
                total_assets += amt
            else:
                total_liabilities += amt

            clean_rows.append({
                "particulars": p_name,
                "ledger_type": l_type,
                "amount": amt,
            })

        return {
            "success": True,
            "report_type": "balance-sheet",
            "report_title": "Balance Sheet",
            "company_name": effective_company,
            "company_id": resolved_cid,
            "ledger_type": ledger_type,
            "total_count": len(clean_rows),
            "total_assets": round(total_assets, 2),
            "total_liabilities": round(total_liabilities, 2),
            "rows": clean_rows[:limit],
            "pagination": pagination_data,
        }

    async def get_company_voucher_lines(
        self,
        voucher_id: str,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        page: int = 1,
        limit: int = 100,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches Voucher Lines from GET /companies/{CompanyId}/reports/voucher-lines?voucherId={voucherId}."""
        comp_details = await self.resolve_company_details(company_name=company_name, company_id=company_id, token=token)
        resolved_cid = comp_details["company_id"]
        effective_company = comp_details["company_name"]

        params: Dict[str, Any] = {"page": page, "limit": limit, "voucherId": voucher_id}
        path = f"/companies/{resolved_cid}/reports/voucher-lines"
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

        raw_rows = []
        if res.get("success") and res.get("data") is not None:
            raw_d = res.get("data")
            if isinstance(raw_d, list):
                raw_rows = raw_d
            elif isinstance(raw_d, dict):
                for k in ["voucherLines", "voucher_lines", "lines", "entries", "items", "records", "rows", "data"]:
                    if isinstance(raw_d.get(k), list):
                        raw_rows = raw_d[k]
                        break

        clean_rows = []
        tot_amt = 0.0
        for it in raw_rows:
            amt = _safe_float(it.get("amount") or 0.0)
            tot_amt += amt
            clean_rows.append({
                "item_name": str(it.get("itemName") or it.get("stockItemName") or it.get("name") or "Item"),
                "quantity": _safe_float(it.get("quantity") or 1.0),
                "rate": _safe_float(it.get("rate") or amt),
                "amount": amt,
                "unit": str(it.get("unit") or "NOS"),
                "hsn_code": str(it.get("hsnCode") or it.get("hsn") or ""),
            })

        return {
            "success": True,
            "report_type": "voucher-lines",
            "report_title": f"Voucher Lines #{voucher_id}",
            "voucher_id": voucher_id,
            "company_name": effective_company,
            "company_id": resolved_cid,
            "total_count": len(clean_rows),
            "total_amount": round(tot_amt, 2),
            "rows": clean_rows[:limit],
        }

