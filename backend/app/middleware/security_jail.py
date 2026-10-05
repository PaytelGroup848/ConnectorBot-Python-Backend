import ipaddress
import logging
import os
from typing import Optional, List, Set
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.core.redis import cache_service

logger = logging.getLogger("connector_ai.security_jail")

BAN_DURATION_SECONDS = 86400  # 24 Hours
STRIKE_THRESHOLD = 3          # 3 Strikes & banned

# Default trusted subnets (Loopback, RFC 1918 Private, Carrier-grade NAT, IPv6 Local)
DEFAULT_WHITELIST_NETWORKS: List[ipaddress._BaseNetwork] = [
    ipaddress.ip_network("127.0.0.0/8"),      # IPv4 Loopback
    ipaddress.ip_network("::1/128"),          # IPv6 Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # Private RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),    # Private RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),   # Private RFC 1918
    ipaddress.ip_network("100.64.0.0/10"),    # Carrier-grade NAT
    ipaddress.ip_network("fc00::/7"),         # IPv6 Unique Local
    ipaddress.ip_network("fe80::/10"),        # IPv6 Link-Local
]

# Explicit infrastructure, gateway, and production host IPs that must NEVER be banned
DEFAULT_WHITELIST_IPS: Set[str] = {
    "127.0.0.1",
    "::1",
    "localhost",
    "191.44.87.1",    # Hosting provider subnet gateway / router
    "191.44.87.206",  # CtrlBooks AI Production server IP
    "210.56.147.234", # Secondary / previous server IP
}


def clean_ip_string(ip_str: str) -> str:
    """Cleans an IP address by trimming whitespace, IPv6 brackets, and port numbers."""
    if not ip_str:
        return "unknown"
    ip_str = ip_str.strip()
    if ip_str.startswith("[") and "]" in ip_str:
        clean_ip = ip_str[1:ip_str.index("]")]
    elif ip_str.count(":") == 1:
        clean_ip = ip_str.split(":")[0]
    else:
        clean_ip = ip_str
    return clean_ip.strip()


def load_whitelist_networks() -> List[ipaddress._BaseNetwork]:
    """Loads additional CIDR networks or IPs from the SECURITY_IP_WHITELIST environment variable."""
    nets = list(DEFAULT_WHITELIST_NETWORKS)
    env_str = os.getenv("SECURITY_IP_WHITELIST", "127.0.0.1,::1,191.44.87.1,191.44.87.206,210.56.147.234")
    for item in env_str.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            if "/" in item:
                nets.append(ipaddress.ip_network(item, strict=False))
            else:
                nets.append(ipaddress.ip_network(f"{item}/32" if ":" not in item else f"{item}/128", strict=False))
        except ValueError:
            logger.warning(f"Could not parse IP/CIDR in whitelist: {item}")
    return nets


CACHED_WHITELIST_NETWORKS = load_whitelist_networks()


def is_ip_whitelisted(ip_str: Optional[str]) -> bool:
    """Checks whether an IP is whitelisted (loopback, private VPC, gateway, or trusted host)."""
    if not ip_str or ip_str in ("unknown", "unknown_ip", "localhost"):
        return True  # Internal / unresolved connections are never banned

    clean_ip = clean_ip_string(ip_str)
    if clean_ip in DEFAULT_WHITELIST_IPS:
        return True

    try:
        ip_obj = ipaddress.ip_address(clean_ip)
        if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local:
            return True
        for net in CACHED_WHITELIST_NETWORKS:
            if ip_obj in net:
                return True
    except ValueError:
        pass
    return False


def get_client_ip(request: Request) -> str:
    """Extracts the true client IP from standard proxy headers or fallback socket."""
    # 1. Cloudflare header
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        cleaned = clean_ip_string(cf_ip)
        try:
            ipaddress.ip_address(cleaned)
            return cleaned
        except ValueError:
            pass

    # 2. X-Real-IP (Nginx standard proxy)
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        cleaned = clean_ip_string(real_ip)
        try:
            ipaddress.ip_address(cleaned)
            return cleaned
        except ValueError:
            pass

    # 3. X-Forwarded-For (Leftmost is client)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [clean_ip_string(p) for p in forwarded.split(",") if p.strip()]
        for p in parts:
            try:
                ipaddress.ip_address(p)
                return p
            except ValueError:
                continue

    # 4. Fallback to direct socket connection
    if request.client and request.client.host:
        return clean_ip_string(request.client.host)

    return "unknown"


async def ban_ip_immediately(client_ip: str, reason: str, duration: int = BAN_DURATION_SECONDS):
    """Instantly blacklists a hostile IP address across the platform."""
    if is_ip_whitelisted(client_ip):
        logger.info(f"🛡️ [SECURITY JAIL BYPASS] Ban skipped for whitelisted/trusted IP {client_ip}. Reason: {reason}")
        return

    ban_key = f"jail:banned:ip:{client_ip}"
    await cache_service.client.set(ban_key, reason, ex=duration)
    logger.critical(f"🚨 [IP AUTO-BANNED] IP {client_ip} has been jailed for 24h. Reason: {reason}")


async def record_strike(client_ip: str, reason: str):
    """Records an attack strike against an IP. Jails after 3 strikes."""
    if is_ip_whitelisted(client_ip):
        logger.debug(f"🛡️ [SECURITY JAIL BYPASS] Strike skipped for whitelisted IP {client_ip}.")
        return

    strike_key = f"jail:strikes:ip:{client_ip}"
    strikes = await cache_service.client.incr(strike_key)
    if strikes == 1:
        await cache_service.client.expire(strike_key, 3600)  # 1 hour window

    logger.warning(f"⚠️ [STRIKE {strikes}/{STRIKE_THRESHOLD}] IP: {client_ip}. Reason: {reason}")
    if strikes >= STRIKE_THRESHOLD:
        await ban_ip_immediately(client_ip, f"Exceeded {STRIKE_THRESHOLD} attack strikes ({reason})")


async def is_ip_banned(client_ip: str) -> bool:
    """Checks whether an IP is banned in Redis. Whitelisted IPs always return False."""
    if is_ip_whitelisted(client_ip):
        return False
    ban_key = f"jail:banned:ip:{client_ip}"
    val = await cache_service.client.get(ban_key)
    return bool(val)


class SecurityJailMiddleware(BaseHTTPMiddleware):
    """Interception middleware that terminates requests from banned hacker IPs instantly."""
    async def dispatch(self, request: Request, call_next):
        client_ip = get_client_ip(request)

        # 1. Trusted / Whitelisted IPs (Loopback, Gateway, Subnets) always pass through
        if is_ip_whitelisted(client_ip):
            return await call_next(request)

        # 2. Check if IP is in the Jail
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
