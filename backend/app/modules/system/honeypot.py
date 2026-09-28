from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.security_event import SecurityEvent
from app.middleware.security_jail import ban_ip_immediately

router = APIRouter(tags=["Security Decoys & Honeypots"])

HONEYPOT_PATHS = [
    "/.env",
    "/wp-login.php",
    "/phpmyadmin",
    "/api/v1/debug/dump-database",
    "/.git/config",
]


async def handle_honeypot(request: Request, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path
    request_id = getattr(request.state, "request_id", "req_trap")

    # 1. Immediately Jail the Hostile Attacker IP for 24 Hours
    await ban_ip_immediately(client_ip, reason=f"Hostile Honeypot Scanner hit: {path}")

    # 2. Log Critical Security Incident in PostgreSQL
    event = SecurityEvent(
        event_type="HONEYPOT_TRIGGERED",
        severity="CRITICAL",
        request_id=request_id,
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "unknown"),
        resource_type="DECOY_TRAP",
        resource_id=path,
        metadata_={"method": request.method, "raw_url": str(request.url)},
    )
    db.add(event)
    await db.commit()

    # 3. Return Troll Trap Warning Response
    return {
        "success": False,
        "warning": "🖕 TRAP TRIGGERED! NICE TRY HACKER.",
        "error": {
            "code": "HONEYPOT_ACTIVATED",
            "message": "You touched a restricted security decoy. Your IP address has been logged and banned for 24 hours.",
            "target": path,
        },
        "request_id": request_id,
    }


# Register all decoy paths
for p in HONEYPOT_PATHS:
    router.add_api_route(
        path=p,
        endpoint=handle_honeypot,
        methods=["GET", "POST"],
        include_in_schema=False,
    )

