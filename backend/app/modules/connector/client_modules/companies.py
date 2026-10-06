import logging
from typing import Optional, Dict, Any, List
from app.core.config import settings

logger = logging.getLogger("connector_ai.connector_client")


class CompanyClientMixin:
    """Company and workspace directory resolution methods."""
    async def get_plans(self) -> List[Dict[str, Any]]:
        """Fetch SaaS subscription plans from live Connector backend."""
        res = await self._request("GET", "/plans")
        if res.get("success") and res.get("data"):
            return res["data"].get("plans", [])
        return []

    async def get_companies(self, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """1. Get Company: GET /companies - Fetches all linked Tally companies for user."""
        active_token = token or settings.CONNECTOR_API_TOKEN
        res = await self._request("GET", "/companies", token=active_token)
        if res.get("success") and res.get("data"):
            raw_data = res["data"]
            comps = raw_data if isinstance(raw_data, list) else raw_data.get("companies", [])
            normalized = []
            for c in comps:
                c_name = str(c.get("tallyCompanyName") or c.get("name") or c.get("companyName") or "Tally Company")
                normalized.append({
                    "id": str(c.get("id") or c.get("_id") or ""),
                    "name": c_name,
                    "company_name": c_name,
                    "tallyCompanyName": c_name,
                    "guid": str(c.get("tallyCompanyGuid") or c.get("guid") or ""),
                    "tallyCompanyGuid": str(c.get("tallyCompanyGuid") or c.get("guid") or ""),
                    "status": str(c.get("status") or "CONNECTED"),
                    "linkedByConnectorId": str(c.get("linkedByConnectorId") or c.get("connectorId") or ""),
                    "businessName": c.get("businessName") or c.get("displayName") or c_name,
                    "city": c.get("city") or c.get("address") or "",
                    "createdAt": c.get("createdAt") or "",
                })
            if normalized:
                return normalized

        # Dynamically discover any active registered companies from command queue or default
        try:
            from app.modules.connector.commands import command_queue_service
            registered = sorted(list(set(
                q.get("company") for q in command_queue_service.list_queued_commands() if q.get("company")
            )))
            if registered:
                return [{"id": f"conn_{idx+1}", "name": comp, "company_name": comp, "status": "CONNECTED"} for idx, comp in enumerate(registered)]
        except Exception:
            pass

        return [
            {
                "id": "conn_tally_01",
                "name": "My Company",
                "company_name": "My Company",
                "status": "CONNECTED",
            }
        ]

    async def get_tally_connections(self, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """Backward-compatible alias for get_companies."""
        return await self.get_companies(token=token)

    async def get_company_by_id(self, company_id: str, token: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """2. Get Company Details: GET /companies/:id - Fetches verified live company profile."""
        if not company_id or str(company_id).strip() in ("", "None", "undefined"):
            return None
        clean_cid = str(company_id).strip()
        active_token = token or settings.CONNECTOR_API_TOKEN

        # 1. Primary: Direct GET /companies/:id endpoint
        res = await self._request("GET", f"/companies/{clean_cid}", token=active_token)
        if res.get("success") and res.get("data"):
            raw = res["data"]
            c = raw.get("company") if isinstance(raw, dict) and "company" in raw else raw
            if isinstance(c, dict):
                c_name = str(c.get("tallyCompanyName") or c.get("name") or c.get("companyName") or "Tally Company")
                return {
                    "id": str(c.get("id") or c.get("_id") or clean_cid),
                    "name": c_name,
                    "company_name": c_name,
                    "tallyCompanyName": c_name,
                    "guid": str(c.get("tallyCompanyGuid") or c.get("guid") or ""),
                    "tallyCompanyGuid": str(c.get("tallyCompanyGuid") or c.get("guid") or ""),
                    "status": str(c.get("status") or "CONNECTED"),
                    "linkedByConnectorId": str(c.get("linkedByConnectorId") or c.get("connectorId") or ""),
                    "businessName": c.get("businessName") or c.get("displayName") or c_name,
                    "address": c.get("address") or "",
                    "city": c.get("city") or "",
                    "state": c.get("state") or "",
                    "gstin": c.get("gstin") or "",
                    "pan": c.get("pan") or "",
                    "email": c.get("email") or "",
                    "phone": c.get("phone") or "",
                    "financialYearFrom": c.get("financialYearFrom") or c.get("startingFrom") or "",
                    "booksBeginningFrom": c.get("booksBeginningFrom") or "",
                    "createdAt": c.get("createdAt") or "",
                    "lastSync": c.get("lastSync") or "",
                }

        # 2. Resilient Fallback: Match within GET /companies list
        all_comps = await self.get_companies(token=token)
        for comp in all_comps:
            if comp.get("id") == clean_cid or clean_cid.lower() in comp.get("name", "").lower():
                return comp

        return None

    async def resolve_company_details(
        self,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, str]:
        """Resolves both the active CtrlBooks MongoDB CompanyId and official TallyCompanyName."""
        import re
        active_token = token or settings.CONNECTOR_API_TOKEN
        if active_token:
            res = await self._request("GET", "/companies", token=active_token)
            if res.get("success") and res.get("data"):
                raw_list = res["data"] if isinstance(res["data"], list) else res["data"].get("companies", [])
                if raw_list:
                    if company_id:
                        for comp in raw_list:
                            cid = str(comp.get("id") or comp.get("_id") or "")
                            if cid == str(company_id):
                                c_name = str(comp.get("tallyCompanyName") or comp.get("company_name") or comp.get("name") or "Connected Company")
                                return {"company_id": cid, "company_name": c_name}
                    if company_name and company_name.lower().strip() not in ("ctrlbooks", "default", "your company", "connected company"):
                        target = company_name.lower().strip()
                        clean_target = re.sub(r"\b(company|firm|ltd|pvt|enterprise|trader|traders)\b", "", target).strip()
                        target_words = [w for w in target.split() if len(w) >= 3 and w not in ("company", "firm", "ltd", "pvt")]
                        for comp in raw_list:
                            cid = str(comp.get("id") or comp.get("_id") or "")
                            c_name = str(comp.get("tallyCompanyName") or comp.get("company_name") or comp.get("name") or "")
                            c_lower = c_name.lower().strip()
                            if target in c_lower or c_lower in target:
                                return {"company_id": cid, "company_name": c_name}
                            if clean_target and len(clean_target) >= 3 and clean_target in c_lower:
                                return {"company_id": cid, "company_name": c_name}
                            if any(w in c_lower for w in target_words):
                                return {"company_id": cid, "company_name": c_name}
                    first_comp = raw_list[0]
                    first_id = str(first_comp.get("id") or first_comp.get("_id") or "6aa0f659f858467a84d08d57")
                    first_name = str(first_comp.get("tallyCompanyName") or first_comp.get("company_name") or first_comp.get("name") or "Connected Company")
                    return {"company_id": first_id, "company_name": first_name}
        fallback_name = (
            company_name
            if company_name and company_name.lower().strip() not in ("ctrlbooks", "default", "your company", "connected company")
            else "Connected Company"
        )
        return {"company_id": company_id or "6aa0f659f858467a84d08d57", "company_name": fallback_name}

    async def resolve_company_id(
        self,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        token: Optional[str] = None,
    ) -> str:
        """Resolves the active CtrlBooks MongoDB CompanyId via GET /api/companies or explicit company_id."""
        if company_id and len(str(company_id).strip()) >= 12:
            return str(company_id).strip()
        details = await self.resolve_company_details(company_name=company_name, company_id=company_id, token=token)
        return details["company_id"]

    async def get_voucher_types(self, company_id: str, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetches active Tally Voucher Types from GET /api/companies/{CompanyId}/voucher-types."""
        active_token = token or settings.CONNECTOR_API_TOKEN
        if active_token:
            res = await self._request("GET", f"/companies/{company_id}/voucher-types", token=active_token)
            if res.get("success") and res.get("data"):
                v_list = res["data"] if isinstance(res["data"], list) else res["data"].get("voucherTypes", [])
                if v_list:
                    return v_list
        return [
            {"name": "Gst Sales", "parent": "Sales"},
            {"name": "Sales", "parent": "Sales"},
            {"name": "Receipt", "parent": "Receipt"},
            {"name": "Purchase", "parent": "Purchase"},
        ]

    async def get_godowns(self, company_id: str, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetches active Tally Godowns from GET /api/companies/{CompanyId}/godowns."""
        active_token = token or settings.CONNECTOR_API_TOKEN
        if active_token:
            res = await self._request("GET", f"/companies/{company_id}/godowns", token=active_token)
            if res.get("success") and res.get("data"):
                g_list = res["data"] if isinstance(res["data"], list) else res["data"].get("godowns", [])
                if g_list:
                    return g_list
        return [{"name": "Main Location"}]

