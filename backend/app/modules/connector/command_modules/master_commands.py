import datetime
import logging
from typing import Dict, Any, Optional, List
from app.modules.connector.client import connector_client

logger = logging.getLogger("connector_ai.commands")


class MasterCommandMixin:
    """Master ledger, inventory item, unit creation, and voucher cancellation commands."""
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

