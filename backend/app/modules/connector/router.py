import datetime
from fastapi import APIRouter, Depends, Request
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.modules.connector.commands import command_queue_service
from app.modules.connector.client import connector_client
from app.middleware.tenant_context import TenantContext, get_current_tenant_context

router = APIRouter(prefix="/api/v1/connector", tags=["Tally Prime & CtrlBooks 2-Way Engine"])


class SalesVoucherCreateRequest(BaseModel):
    company_name: Optional[str] = Field(None, description="Tally company name")
    party_ledger: str = Field(..., description="Customer / debtor party ledger name")
    date: str = Field(default_factory=lambda: datetime.date.today().isoformat(), description="Invoice date YYYY-MM-DD")
    total_amount: float = Field(..., gt=0, description="Taxable amount in INR")
    items: Optional[List[Dict[str, Any]]] = Field(None, description="Voucher line items")
    narration: Optional[str] = Field(None, description="Voucher narration")


class ReceiptVoucherCreateRequest(BaseModel):
    company_name: Optional[str] = Field(None, description="Tally company name")
    party_ledger: str = Field(..., description="Customer party ledger name")
    bank_or_cash_ledger: str = Field("Bank Account", description="Bank or Cash ledger")
    amount: float = Field(..., gt=0, description="Receipt amount in INR")
    date: str = Field(default_factory=lambda: datetime.date.today().isoformat(), description="Receipt date YYYY-MM-DD")
    reference_no: Optional[str] = Field(None, description="Cheque or UPI reference")


@router.get("/queue", response_model=dict, summary="View all vouchers in CtrlBooks 2-Way Command Queue")
async def list_voucher_queue(request: Request):
    """Returns all vouchers created by the AI or users waiting to sync to Tally Prime."""
    request_id = getattr(request.state, "request_id", "req_queue")
    items = command_queue_service.list_queued_commands()
    return {
        "success": True,
        "data": {
            "total_queued": len(items),
            "items": items,
        },
        "error": None,
        "request_id": request_id,
    }


@router.post("/vouchers/sales", response_model=dict, summary="Directly create and queue a Sales Voucher")
async def create_sales_voucher(
    payload: SalesVoucherCreateRequest,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
):
    request_id = getattr(request.state, "request_id", "req_vouch_sales")
    v_items = payload.items or [{
        "name": f"Sales - {payload.party_ledger}",
        "quantity": 1,
        "rate": payload.total_amount,
        "amount": payload.total_amount,
    }]
    v_narration = payload.narration or f"Sales invoice for {payload.party_ledger}"
    result = await command_queue_service.create_sales_invoice(
        company_name=payload.company_name or "Default",
        party_ledger=payload.party_ledger,
        date=payload.date,
        items=v_items,
        total_amount=payload.total_amount,
        narration=v_narration,
    )
    return {
        "success": True,
        "data": result,
        "error": None,
        "request_id": request_id,
    }


@router.post("/vouchers/receipt", response_model=dict, summary="Directly create and queue a Receipt Voucher")
async def create_receipt_voucher(
    payload: ReceiptVoucherCreateRequest,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
):
    request_id = getattr(request.state, "request_id", "req_vouch_rec")
    result = await command_queue_service.create_receipt(
        company_name=payload.company_name,
        party_ledger=payload.party_ledger,
        bank_or_cash_ledger=payload.bank_or_cash_ledger,
        amount=payload.amount,
        date=payload.date,
        reference_no=payload.reference_no,
    )
    return {
        "success": True,
        "data": result,
        "error": None,
        "request_id": request_id,
    }


class AgentHeartbeatRequest(BaseModel):
    tally_port: int = Field(..., ge=1, le=65535, description="Active Tally Prime ODBC/XML Server port")
    company_name: Optional[str] = Field(None, description="Company name linked to this Tally instance")
    user_email: Optional[str] = Field(None, description="Logged-in CtrlBooks user email")
    is_online: bool = Field(True, description="Whether Tally Prime is responding on the port")
    agent_version: str = Field("1.0.1", description="Desktop Connector Agent version")


@router.post("/heartbeat", response_model=dict, summary="Register Desktop Agent or CtrlBooks User Tally Port Heartbeat")
async def register_agent_heartbeat(payload: AgentHeartbeatRequest, request: Request):
    request_id = getattr(request.state, "request_id", "req_heartbeat")
    record = connector_client.register_heartbeat(
        tally_port=payload.tally_port,
        company_name=payload.company_name,
        user_email=payload.user_email,
        is_online=payload.is_online,
        agent_version=payload.agent_version,
    )
    return {
        "success": True,
        "data": record,
        "error": None,
        "request_id": request_id,
    }


@router.get("/status", response_model=dict, summary="Check live Tally Prime & Connector connection dynamically")
async def check_tally_status(
    request: Request,
    company_name: Optional[str] = None,
    user_email: Optional[str] = None,
    tally_port: Optional[int] = None,
):
    request_id = getattr(request.state, "request_id", "req_conn_status")
    status = await connector_client.get_connection_status(
        company_name=company_name,
        user_email=user_email,
        preferred_port=tally_port,
    )
    return {
        "success": True,
        "data": status,
        "error": None,
        "request_id": request_id,
    }


@router.get("/companies", response_model=dict, summary="Get list of available Tally companies")
async def list_companies(
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
):
    request_id = getattr(request.state, "request_id", "req_companies")
    companies = await connector_client.get_tally_connections()
    return {"success": True, "data": companies, "error": None, "request_id": request_id}


@router.get("/dashboard/metrics", response_model=dict, summary="Get CtrlBooks financial KPIs and recent activity")
async def get_dashboard_metrics(company_name: Optional[str] = None, request: Request = None):
    request_id = getattr(request.state, "request_id", "req_metrics") if request else "req_metrics"
    
    queued = command_queue_service.list_queued_commands()
    comp_vouchers = [
        q for q in queued 
        if not company_name or (q.get("company") and company_name.lower() in q.get("company", "").lower())
    ]
    
    sales_vouchers = [
        v for v in comp_vouchers
        if v.get("command_type") == "CREATE_VOUCHER" or v.get("payload", {}).get("payload", {}).get("voucher_type") == "Sales"
    ]
    
    total_sales = sum(
        v.get("payload", {}).get("payload", {}).get("amount", 0.0) 
        for v in sales_vouchers
    )
    
    dynamic_invoices = []
    for v in sales_vouchers:
        p = v.get("payload", {}).get("payload", {})
        dynamic_invoices.append({
            "number": v.get("voucher_number", "INV-NEW"),
            "party": p.get("party_ledger", "Party"),
            "amount": p.get("amount", 0.0),
            "due_date": p.get("date", datetime.date.today().isoformat()),
        })

    receivables_total = sum(i["amount"] for i in dynamic_invoices)
    
    payables_vouchers = [
        v for v in comp_vouchers
        if v.get("command_type") in ("CREATE_PURCHASE", "CREATE_PAYMENT")
    ]
    payables_total = sum(
        v.get("payload", {}).get("payload", {}).get("amount", 0.0)
        for v in payables_vouchers
    )
    
    # Calculate actual GST from ledger entries
    gst_total = sum(
        entry.get("amount", 0.0)
        for v in sales_vouchers
        for entry in v.get("payload", {}).get("payload", {}).get("ledger_entries", [])
        if "GST" in entry.get("ledger", "").upper()
    )

    metrics = {
        "company_name": company_name or "Default",
        "sales": {
            "total": round(total_sales, 2),
            "change_pct": round(len(sales_vouchers) * 5.0, 1) if sales_vouchers else 0.0,
            "period": datetime.date.today().strftime("%b %Y"),
            "trend": [round(total_sales, 2)] if total_sales > 0 else [0.0],
        },
        "receivables": {
            "total": round(receivables_total, 2),
            "count": len(dynamic_invoices),
            "oldest_days": 0,
            "invoices": dynamic_invoices,
        },
        "payables": {
            "total": round(payables_total, 2),
            "count": len(payables_vouchers),
            "period": datetime.date.today().strftime("%b %Y"),
        },
        "gst_due": {
            "total": round(gst_total, 2),
            "period": datetime.date.today().strftime("%b %Y"),
            "gstr1_status": "Pending Sync" if sales_vouchers else "All Clear",
            "gstr3b_status": "Pending Filing" if gst_total > 0 else "Filed",
        },
        "recent_activity": [
            {
                "id": f"act_{v.get('voucher_number', 'v')}",
                "type": "invoice_created",
                "title": f"Voucher #{v.get('voucher_number', 'INV')}",
                "subtitle": f"Queued ₹{v.get('payload', {}).get('payload', {}).get('amount', 0):,.2f} • {v.get('payload', {}).get('payload', {}).get('party_ledger', 'Party')}",
                "time": "Just now",
                "badge": "QUEUED",
            }
            for v in reversed(comp_vouchers[-5:])
        ],
    }
    return {"success": True, "data": metrics, "error": None, "request_id": request_id}


