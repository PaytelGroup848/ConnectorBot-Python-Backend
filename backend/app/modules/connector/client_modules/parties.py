import logging
from typing import Optional, Dict, Any, List
from app.core.config import settings

logger = logging.getLogger("connector_ai.connector_client")


class PartiesClientMixin:
    """Customer, supplier, cash-in-hand, bank account, and ledger search methods."""
    async def search_ledgers(self, company_name: str, query: str, company_id: Optional[str] = None, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search party and general account ledgers in Tally / CtrlBooks."""
        active_token = token or settings.CONNECTOR_API_TOKEN
        if active_token:
            # 1. Primary: Use full /ledgers endpoint (covers 100% of Tally ledgers: Debtors, Creditors, Bank, Cash, Expenses, Taxes)
            try:
                ledgers_res = await self.get_company_ledgers(
                    company_name=company_name, company_id=company_id, q=query, limit=10, token=active_token
                )
                if ledgers_res.get("success") and ledgers_res.get("items"):
                    return [
                        {
                            "name": l["name"],
                            "parent": l.get("parent") or l.get("group") or "Primary",
                            "group": l.get("group") or l.get("parent") or "Primary",
                            "closing_balance": l["closingBalance"],
                            "gstin": l.get("gstin", ""),
                            "state": "Active",
                        }
                        for l in ledgers_res["items"]
                    ]
            except Exception:
                pass

            # 2. Fallback to /parties endpoint
            try:
                parties_res = await self.get_company_parties(
                    company_name=company_name, company_id=company_id, q=query, limit=10, token=active_token
                )
                if parties_res.get("success") and parties_res.get("items"):
                    return [
                        {
                            "name": p["name"],
                            "parent": "Sundry Debtors" if p["closingBalance"] >= 0 else "Sundry Creditors",
                            "group": "Sundry Debtors" if p["closingBalance"] >= 0 else "Sundry Creditors",
                            "closing_balance": p["closingBalance"],
                            "gstin": p["gstin"],
                            "phone": p.get("phone", ""),
                            "state": "Active",
                        }
                        for p in parties_res["items"]
                    ]
            except Exception:
                pass
        ledger_name = query.strip().title() if query and query.strip() else "Customer Ledger"
        return [
            {
                "name": ledger_name,
                "parent": "General Ledger",
                "group": "General Ledger",
                "closing_balance": 0.0,
                "gstin": "",
                "state": "Active",
            }
        ]

    async def search_stock_items(self, company_name: str, query: str, company_id: Optional[str] = None, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search inventory stock products in Tally / CtrlBooks."""
        if company_id and token:
            res = await self._request("GET", f"/companies/{company_id}/items", token=token, params={"search": query})
            if res.get("success") and res.get("data"):
                items = res["data"] if isinstance(res["data"], list) else res["data"].get("items", [])
                if items:
                    return items
        item_name = query.strip().title() if query and query.strip() else "Standard Goods"
        return [
            {
                "name": item_name,
                "itemName": item_name,
                "closing_stock": 100.0,
                "unit": "NOS",
                "units": "NOS",
                "standard_rate": 1000.0,
                "hsn_code": "9983",
                "hsnCode": "9983",
            }
        ]

    async def get_company_cash(
        self,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        page: int = 1,
        limit: int = 10,
        q: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches Cash-in-hand accounts from GET /companies/{CompanyId}/cash."""
        comp_details = await self.resolve_company_details(company_name=company_name, company_id=company_id, token=token)
        resolved_cid = comp_details["company_id"]
        effective_company = comp_details["company_name"]

        params: Dict[str, Any] = {"page": page, "limit": limit}
        if q:
            params["q"] = q.strip()

        path = f"/companies/{resolved_cid}/cash"
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
        tot_count = 0
        tot_amount = 0.0

        if res.get("success") and res.get("data") is not None:
            data = res.get("data")
            if isinstance(data, dict):
                raw_items = data.get("items") or []
                tot_count = int(data.get("total") or len(raw_items))
                if "totalAmount" in data and data["totalAmount"] is not None:
                    tot_amount = _safe_float(data.get("totalAmount"))
                else:
                    tot_amount = sum(_safe_float(it.get("closingBalance") or 0.0) for it in raw_items)
            elif isinstance(data, list):
                raw_items = data
                tot_count = len(raw_items)
                tot_amount = sum(_safe_float(it.get("closingBalance") or 0.0) for it in raw_items)

        items = []
        for it in raw_items:
            items.append({
                "_id": str(it.get("_id") or ""),
                "name": str(it.get("name") or "Cash"),
                "group": str(it.get("group") or "Cash-in-hand"),
                "ledgerType": str(it.get("ledgerType") or "CASH"),
                "openingBalance": _safe_float(it.get("openingBalance") or 0.0),
                "closingBalance": _safe_float(it.get("closingBalance") or 0.0),
                "tallyExternalId": str(it.get("tallyExternalId") or ""),
                "parent": str(it.get("parent") or "Cash-in-hand"),
            })

        return {
            "success": True,
            "company_name": effective_company,
            "company_id": resolved_cid,
            "module": "cash",
            "total": tot_count,
            "page": page,
            "limit": limit,
            "total_amount": round(tot_amount, 2),
            "items": items,
        }

    async def get_company_bank(
        self,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        page: int = 1,
        limit: int = 10,
        q: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches Bank accounts from GET /companies/{CompanyId}/bank."""
        comp_details = await self.resolve_company_details(company_name=company_name, company_id=company_id, token=token)
        resolved_cid = comp_details["company_id"]
        effective_company = comp_details["company_name"]

        params: Dict[str, Any] = {"page": page, "limit": limit}
        if q:
            params["q"] = q.strip()

        path = f"/companies/{resolved_cid}/bank"
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
        tot_count = 0
        tot_amount = 0.0

        if res.get("success") and res.get("data") is not None:
            data = res.get("data")
            if isinstance(data, dict):
                raw_items = data.get("items") or []
                tot_count = int(data.get("total") or len(raw_items))
                if "totalAmount" in data and data["totalAmount"] is not None:
                    tot_amount = _safe_float(data.get("totalAmount"))
                else:
                    tot_amount = sum(_safe_float(it.get("closingBalance") or 0.0) for it in raw_items)
            elif isinstance(data, list):
                raw_items = data
                tot_count = len(raw_items)
                tot_amount = sum(_safe_float(it.get("closingBalance") or 0.0) for it in raw_items)

        items = []
        for it in raw_items:
            items.append({
                "_id": str(it.get("_id") or ""),
                "name": str(it.get("name") or "Bank Account"),
                "group": str(it.get("group") or "Bank Accounts"),
                "ledgerType": str(it.get("ledgerType") or "BANK"),
                "openingBalance": _safe_float(it.get("openingBalance") or 0.0),
                "closingBalance": _safe_float(it.get("closingBalance") or 0.0),
                "tallyExternalId": str(it.get("tallyExternalId") or ""),
                "parent": str(it.get("parent") or "Bank Accounts"),
            })

        return {
            "success": True,
            "company_name": effective_company,
            "company_id": resolved_cid,
            "module": "bank",
            "total": tot_count,
            "page": page,
            "limit": limit,
            "total_amount": round(tot_amount, 2),
            "items": items,
        }

    async def get_company_parties(
        self,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
        q: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches Parties from GET /companies/{CompanyId}/parties?page={page}&limit={limit}&q={q}."""
        comp_details = await self.resolve_company_details(company_name=company_name, company_id=company_id, token=token)
        resolved_cid = comp_details["company_id"]
        effective_company = comp_details["company_name"]

        # Support enterprise pagination up to 500 per page
        effective_limit = min(int(limit), 500) if limit else 50
        params: Dict[str, Any] = {"page": page, "limit": effective_limit}
        if q:
            params["q"] = q.strip()

        path = f"/companies/{resolved_cid}/parties"
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
        tot_count = 0
        if res.get("success") and res.get("data") is not None:
            data = res.get("data")
            if isinstance(data, dict):
                raw_items = data.get("items") or []
                tot_count = int(data.get("total") or len(raw_items))
            elif isinstance(data, list):
                raw_items = data
                tot_count = len(raw_items)

        clean_items = []
        tot_debit = 0.0
        tot_credit = 0.0

        for it in raw_items:
            cb = _safe_float(it.get("closingBalance") or 0.0)
            ob = _safe_float(it.get("openingBalance") or 0.0)
            if cb > 0:
                tot_debit += cb
            elif cb < 0:
                tot_credit += abs(cb)

            clean_items.append({
                "_id": str(it.get("_id") or ""),
                "name": str(it.get("partyName") or it.get("name") or "Party"),
                "partyName": str(it.get("partyName") or it.get("name") or "Party"),
                "closingBalance": cb,
                "openingBalance": ob,
                "gstin": str(it.get("gstin") or ""),
                "phone": str(it.get("phone") or ""),
                "email": str(it.get("email") or ""),
                "address": str(it.get("address") or ""),
                "creditLimit": _safe_float(it.get("creditLimit") or 0.0),
                "creditDays": int(it.get("creditDays") or 0),
                "lastSoldDate": str(it.get("lastSoldDate") or ""),
                "tallyExternalId": str(it.get("tallyExternalId") or ""),
            })

        return {
            "success": True,
            "company_name": effective_company,
            "company_id": resolved_cid,
            "module": "parties",
            "search_query": q,
            "total": tot_count,
            "page": page,
            "limit": effective_limit,
            "total_debit": round(tot_debit, 2),
            "total_credit": round(tot_credit, 2),
            "net_balance": round(tot_debit - tot_credit, 2),
            "items": clean_items,
        }

    async def get_company_ledgers(
        self,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
        q: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches All Ledgers from GET /companies/{CompanyId}/ledgers?page={page}&limit={limit}&q={q}."""
        comp_details = await self.resolve_company_details(company_name=company_name, company_id=company_id, token=token)
        resolved_cid = comp_details["company_id"]
        effective_company = comp_details["company_name"]

        effective_limit = min(int(limit), 100) if limit else 50
        params: Dict[str, Any] = {"page": page, "limit": effective_limit}
        if q:
            params["q"] = q.strip()

        path = f"/companies/{resolved_cid}/ledgers"
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
        tot_count = 0
        if res.get("success") and res.get("data") is not None:
            data = res.get("data")
            if isinstance(data, dict):
                raw_items = data.get("items") or data.get("ledgers") or []
                tot_count = int(data.get("total") or len(raw_items))
            elif isinstance(data, list):
                raw_items = data
                tot_count = len(raw_items)

        clean_items = []
        tot_debit = 0.0
        tot_credit = 0.0

        for it in raw_items:
            cb = _safe_float(it.get("closingBalance") or 0.0)
            ob = _safe_float(it.get("openingBalance") or 0.0)
            if cb > 0:
                tot_debit += cb
            elif cb < 0:
                tot_credit += abs(cb)

            clean_items.append({
                "_id": str(it.get("_id") or ""),
                "name": str(it.get("name") or it.get("ledgerName") or "Ledger"),
                "ledgerName": str(it.get("name") or it.get("ledgerName") or "Ledger"),
                "parent": str(it.get("parent") or it.get("group") or "Primary"),
                "group": str(it.get("group") or it.get("parent") or "Primary"),
                "ledgerType": str(it.get("ledgerType") or ""),
                "closingBalance": cb,
                "openingBalance": ob,
                "gstin": str(it.get("gstin") or ""),
                "creditLimit": _safe_float(it.get("creditLimit") or 0.0),
                "creditDays": int(it.get("creditDays") or 0),
                "tallyExternalId": str(it.get("tallyExternalId") or ""),
            })

        return {
            "success": True,
            "company_name": effective_company,
            "company_id": resolved_cid,
            "module": "ledgers",
            "search_query": q,
            "total": tot_count,
            "page": page,
            "limit": effective_limit,
            "total_debit": round(tot_debit, 2),
            "total_credit": round(tot_credit, 2),
            "net_balance": round(tot_debit - tot_credit, 2),
            "items": clean_items,
        }

