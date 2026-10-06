import logging
import datetime
from typing import Optional, Dict, Any, List
import httpx
from app.core.config import settings

logger = logging.getLogger("connector_ai.connector_client")


class VoucherClientMixin:
    """Voucher commands push, XML envelope construction, and voucher history querying."""
    async def push_voucher_command(
        self,
        company_id: str,
        command_payload: Dict[str, Any],
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Pushes a CREATE_VOUCHER command directly to CtrlBooks.com (POST /api/companies/{CompanyId}/commands)
        so the CtrlBooks Web Portal & Desktop Connector Agent immediately sync it into Tally Prime.
        """
        path = f"/companies/{company_id}/commands"
        res = await self._request("POST", path, token=token, json_data=command_payload)
        if res.get("success"):
            cmd_data = res.get("data") or {}
            nested_cmd = cmd_data.get("command") if isinstance(cmd_data.get("command"), dict) else {}
            cmd_id = (
                cmd_data.get("id")
                or cmd_data.get("_id")
                or nested_cmd.get("id")
                or nested_cmd.get("_id")
                or cmd_data.get("commandId")
                or res.get("commandId")
            )
            cmd_status = nested_cmd.get("status") or cmd_data.get("status", "QUEUED")
            return {
                "pushed_to_ctrlbooks": True,
                "ctrlbooks_command_id": cmd_id,
                "ctrlbooks_status": cmd_status,
                "endpoint": f"{self.base_url.rstrip('/')}{path}",
                "raw_response": res,
            }
        return {
            "pushed_to_ctrlbooks": False,
            "ctrlbooks_command_id": None,
            "ctrlbooks_status": "QUEUED_LOCALLY",
            "endpoint": f"{self.base_url.rstrip('/')}{path}",
            "reason": res.get("message") or res.get("error") or f"HTTP {res.get('statusCode', 'Standby')}",
        }

    async def get_command_status(self, command_id: str, token: Optional[str] = None) -> Dict[str, Any]:
        """Checks live Tally execution status via GET /api/commands/{CommandId}."""
        return await self._request("GET", f"/commands/{command_id}", token=token)

    async def get_company_vouchers(
        self,
        company_name: Optional[str] = None,
        company_id: Optional[str] = None,
        voucher_type: Optional[str] = None,
        voucher_number: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 5,
        token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves real-time synchronized vouchers from Tally Prime via CtrlBooks Cloud API
        (GET /api/companies/{CompanyId}/vouchers) with search, filter, and resilient queue fallback.
        """
        resolved_cid = await self.resolve_company_id(company_name=company_name, company_id=company_id, token=token)
        query_params = [f"limit={limit}"]
        if voucher_type:
            query_params.append(f"voucherType={voucher_type}")
        if voucher_number:
            query_params.append(f"voucherNumber={voucher_number}")
        if search:
            query_params.append(f"search={search}")

        qs = f"?{'&'.join(query_params)}" if query_params else ""
        res = await self._request("GET", f"/companies/{resolved_cid}/vouchers{qs}", token=token)
        normalized = []
        if res.get("success") and res.get("data") is not None:
            raw_d = res.get("data")
            if isinstance(raw_d, list):
                items = raw_d
            elif isinstance(raw_d, dict):
                items = (
                    raw_d.get("items")
                    or raw_d.get("vouchers")
                    or raw_d.get("data")
                    or raw_d.get("results")
                    or raw_d.get("rows")
                    or []
                )
            else:
                items = []

            def _safe_float(val, default=0.0) -> float:
                try:
                    if isinstance(val, dict):
                        val = val.get("$numberDecimal") or val.get("value") or default
                    if val is None or val == "":
                        return default
                    return float(str(val).replace(",", "").strip())
                except Exception:
                    return default

            for it in items:
                raw_inv = it.get("inventoryEntries") or it.get("raw", {}).get("inventoryEntries") or []
                raw_lines = it.get("lines") or it.get("raw", {}).get("lines") or []
                clean_items = []
                for idx, inv_it in enumerate(raw_inv):
                    i_name = inv_it.get("itemName") or inv_it.get("stockItemName")
                    if i_name:
                        clean_items.append({
                            "name": i_name,
                            "quantity": _safe_float(inv_it.get("quantity"), 1.0),
                            "rate": _safe_float(inv_it.get("rate"), 0.0),
                            "unit": str(inv_it.get("unit") or "NOS"),
                            "amount": _safe_float(inv_it.get("amount"), 0.0),
                            "hsnCode": str(inv_it.get("hsnCode") or ""),
                        })

                tax_entries = []
                for ln in raw_lines:
                    l_name = str(ln.get("ledgerName") or "")
                    if any(t in l_name.upper() for t in ["CGST", "SGST", "IGST", "TAX", "ROUND"]):
                        tax_entries.append({"ledger": l_name, "amount": abs(_safe_float(ln.get("amount"), 0.0))})

                date_val = str(it.get("date") or it.get("effectiveDate") or "")
                if "T" in date_val:
                    date_val = date_val.split("T")[0]

                v_num = str(it.get("voucherNumber") or it.get("voucher_number") or it.get("reference") or it.get("id") or "N/A")
                v_type = str(it.get("voucherType") or it.get("voucher_type") or "Sales")
                party = str(it.get("partyLedger") or it.get("party_ledger") or "Customer Ledger")
                total_amt = _safe_float(it.get("amount"), 0.0)

                normalized.append({
                    "id": str(it.get("_id") or it.get("voucherId") or it.get("guid") or ""),
                    "voucher_number": v_num,
                    "voucher_type": v_type,
                    "party_ledger": party,
                    "amount": total_amt,
                    "date": date_val,
                    "narration": str(it.get("narration") or ""),
                    "items": clean_items,
                    "tax_entries": tax_entries,
                    "company_name": company_name or it.get("company_name"),
                    "company_id": resolved_cid,
                    "status": "SYNCED",
                })

        # Fallback to local command queue if Cloud API returned empty (e.g. freshly queued items)
        if not normalized:
            try:
                from app.modules.connector.commands import command_queue_service
                for q in reversed(command_queue_service.list_queued_commands()):
                    q_comp = str(q.get("company") or "").lower()
                    if not company_name or company_name.lower() in q_comp or q_comp in company_name.lower():
                        p_load = q.get("payload", {}).get("payload", {})
                        q_party = str(p_load.get("party_ledger") or "")
                        q_vnum = str(q.get("voucher_number") or "")
                        if search and search.lower() not in q_party.lower():
                            continue
                        if voucher_number and voucher_number.lower() not in q_vnum.lower():
                            continue
                        normalized.append({
                            "id": str(q.get("command_id") or q.get("command_hash") or ""),
                            "voucher_number": q_vnum,
                            "voucher_type": str(p_load.get("voucher_type") or "Sales"),
                            "party_ledger": q_party,
                            "amount": float(p_load.get("amount") or 0.0),
                            "date": str(p_load.get("date") or datetime.date.today().isoformat()),
                            "narration": str(p_load.get("narration") or ""),
                            "items": p_load.get("items") or [],
                            "tax_entries": [],
                            "company_name": company_name or q.get("company"),
                            "company_id": resolved_cid,
                            "status": q.get("status", "QUEUED"),
                        })
                        if len(normalized) >= limit:
                            break
            except Exception:
                pass

        return normalized

    def build_tally_voucher_xml(
        self,
        company_name: str,
        voucher_type: str,
        voucher_number: str,
        date_str: str,
        party_ledger: str,
        narration: str,
        total_amount: float,
        taxable_amount: float,
        ledger_entries: List[Dict[str, Any]],
        sales_or_bank_ledger: str = "Sales Account",
    ) -> str:
        """
        Builds a Self-Healing Official Tally Prime <ENVELOPE> XML that:
        1. Auto-creates missing Party, Sales/Bank, and GST Duty Ledgers if they don't exist yet in Tally
        2. Imports a balanced Double-Entry Voucher (Dr Party -Total / Cr Sales +Taxable / Cr GST +Tax)
        """
        clean_date = date_str.replace("-", "").strip()
        if len(clean_date) != 8 or not clean_date.isdigit():
            clean_date = datetime.date.today().strftime("%Y%m%d")

        is_receipt = voucher_type.lower() == "receipt"
        parent_group = "Sundry Debtors"

        # Build auto-master <TALLYMESSAGE> blocks so Tally never rejects with 'Ledger does not exist'
        master_xml_blocks = f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="{party_ledger}" ACTION="Create">
            <NAME.LIST><NAME>{party_ledger}</NAME></NAME.LIST>
            <PARENT>{parent_group}</PARENT>
            <ISBILLWISEON>Yes</ISBILLWISEON>
          </LEDGER>
        </TALLYMESSAGE>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="{sales_or_bank_ledger}" ACTION="Create">
            <NAME.LIST><NAME>{sales_or_bank_ledger}</NAME></NAME.LIST>
            <PARENT>{"Bank Accounts" if is_receipt else "Sales Accounts"}</PARENT>
          </LEDGER>
        </TALLYMESSAGE>"""

        tax_ledger_xml = ""
        for le in ledger_entries:
            l_name = le.get("ledger")
            l_amt = round(float(le.get("amount", 0.0)), 2)
            if l_name and l_name != sales_or_bank_ledger and l_amt > 0:
                master_xml_blocks += f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <LEDGER NAME="{l_name}" ACTION="Create">
            <NAME.LIST><NAME>{l_name}</NAME></NAME.LIST>
            <PARENT>Duties &amp; Taxes</PARENT>
          </LEDGER>
        </TALLYMESSAGE>"""
                tax_ledger_xml += f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{l_name}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>{l_amt:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>"""

        if is_receipt:
            # Receipt: Cr Party (+amount), Dr Bank/Cash (-amount)
            entries_xml = f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{party_ledger}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>{total_amount:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{sales_or_bank_ledger}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>-{total_amount:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>"""
        else:
            # Sales Invoice: Dr Party (-total_amount), Cr Sales (+taxable_amount), Cr Taxes (+tax)
            entries_xml = f"""
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{party_ledger}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>-{total_amount:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{sales_or_bank_ledger}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>{taxable_amount:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>{tax_ledger_xml}"""

        return f"""<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>All Masters</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>{company_name}</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>{master_xml_blocks}
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="{voucher_type}" ACTION="Create" OBJVIEW="Accounting Voucher View">
            <DATE>{clean_date}</DATE>
            <VOUCHERTYPENAME>{voucher_type}</VOUCHERTYPENAME>
            <VOUCHERNUMBER>{voucher_number}</VOUCHERNUMBER>
            <PARTYLEDGERNAME>{party_ledger}</PARTYLEDGERNAME>
            <NARRATION>{narration}</NARRATION>
            <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>{entries_xml}
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

    async def push_direct_tally_xml(self, xml_payload: str, preferred_port: Optional[int] = None) -> Dict[str, Any]:
        """If a local Tally Prime HTTP XML server is listening on localhost, pushes the voucher XML immediately."""
        live_port, _ = await self._auto_detect_local_tally_port(preferred_port)
        if not live_port:
            return {"pushed_to_local_tally": False, "tally_port": None, "status": "STANDBY_QUEUED"}
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.post(
                    f"http://127.0.0.1:{live_port}",
                    content=xml_payload.encode("utf-8"),
                    headers={"Content-Type": "text/xml; charset=utf-8"},
                )
                body_text = res.text or ""
                created_ok = "<CREATED>1</CREATED>" in body_text or "<ALTERED>1</ALTERED>" in body_text
                return {
                    "pushed_to_local_tally": created_ok,
                    "tally_port": live_port,
                    "status": "SYNCED_TO_TALLY" if created_ok else "TALLY_RESPONSE_RECEIVED",
                    "raw_xml_response": body_text[:400],
                }
        except Exception as e:
            return {"pushed_to_local_tally": False, "tally_port": live_port, "status": "QUEUED", "error": str(e)}

