import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.core.redis import cache_service

logger = logging.getLogger("connector_ai.security_jail")

BAN_DURATION_SECONDS = 86400  # 24 Hours
STRIKE_THRESHOLD = 3          # 3 Strikes & banned


async def ban_ip_immediately(client_ip: str, reason: str, duration: int = BAN_DURATION_SECONDS):
    """Instantly blacklists a hostile IP address across the platform."""
    ban_key = f"jail:banned:ip:{client_ip}"
    await cache_service.client.set(ban_key, reason, ex=duration)
    logger.critical(f"🚨 [IP AUTO-BANNED] IP {client_ip} has been jailed for 24h. Reason: {reason}")


async def record_strike(client_ip: str, reason: str):
    """Records an attack strike against an IP. Jails after 3 strikes."""
    strike_key = f"jail:strikes:ip:{client_ip}"
    strikes = await cache_service.client.incr(strike_key)
    if strikes == 1:
        await cache_service.client.expire(strike_key, 3600)  # 1 hour window

    logger.warning(f"⚠️ [STRIKE {strikes}/{STRIKE_THRESHOLD}] IP: {client_ip}. Reason: {reason}")
    if strikes >= STRIKE_THRESHOLD:
        await ban_ip_immediately(client_ip, f"Exceeded {STRIKE_THRESHOLD} attack strikes ({reason})")


async def is_ip_banned(client_ip: str) -> bool:
    ban_key = f"jail:banned:ip:{client_ip}"
    val = await cache_service.client.get(ban_key)
    return bool(val)


class SecurityJailMiddleware(BaseHTTPMiddleware):
    """Interception middleware that terminates requests from banned hacker IPs instantly."""
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"

        # Check if IP is in the Jail
        if await is_ip_banned(client_ip):
            request_id = getattr(request.state, "request_id", "req_blocked")
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "data": None,
                    "warning": "🖕 ACCESS DENIED! NICE TRY HACKER.",
                    "error": {
                        "code": "IP_BANNED",
                        "message": "Your IP has been blacklisted for 24 hours due to hostile attack behavior.",
                    },
                    "request_id": request_id,
                },
            )

        return await call_next(request)

