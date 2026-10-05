import re
import logging
from typing import Tuple, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.middleware.security_jail import (
    record_strike,
    ban_ip_immediately,
    is_ip_banned,
    get_client_ip,
    is_ip_whitelisted,
)

logger = logging.getLogger("connector_ai.waf_shield")

# Compiled High-Precision Attack Signatures
ATTACK_PATTERNS = [
    # 1. SQL Injection
    (
        "SQL_INJECTION",
        re.compile(
            r"(?i)(\b(union\s+select|select\s+.*\s+from|insert\s+into|delete\s+from|drop\s+table|update\s+.*\s+set)\b|"
            r"'\s*or\s+['\"\d\w]+=['\"\d\w]+|--\s*$|/\*.*?\*/|"
            r"\b(sleep\s*\(\s*\d+\s*\)|benchmark\s*\(\s*\d+|information_schema)\b)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    # 2. Cross-Site Scripting (XSS)
    (
        "XSS_ATTACK",
        re.compile(
            r"(?i)(<script[\s>]|javascript\s*:|onerror\s*=|onload\s*=|document\.cookie|<iframe[\s>]|eval\s*\(|alert\s*\()",
            re.IGNORECASE,
        ),
    ),
    # 3. Path Traversal / LFI
    (
        "PATH_TRAVERSAL",
        re.compile(
            r"(\.\./|\.\.\\|/etc/passwd|/etc/shadow|[a-zA-Z]:\\[wW]indows|win\.ini|boot\.ini)",
            re.IGNORECASE,
        ),
    ),
    # 4. Remote Command Execution (RCE)
    (
        "COMMAND_INJECTION",
        re.compile(
            r"(?i)(;\s*(cat|ls|rm|chmod|curl|wget|bash|sh|powershell|cmd\.exe|whoami|id)\b|"
            r"\|\s*(cat|ls|whoami|curl|powershell)|`whoami`|\$\(whoami\))",
            re.IGNORECASE,
        ),
    ),
    # 5. SSTI & Log4Shell
    (
        "SSTI_LOG4J",
        re.compile(
            r"(\{\{.*?\}\}|\$\{jndi:(ldap|rmi|dns)|(\$|\#)\{.*?env.*?\})",
            re.IGNORECASE,
        ),
    ),
    # 6. AI Prompt Hijack / System Prompt Theft
    (
        "AI_PROMPT_INJECTION",
        re.compile(
            r"(?i)\b(ignore\s+(all\s+)?previous\s+instructions|system\s+override|reveal\s+(system\s+prompt|all\s+secrets)|disregard\s+all\s+prior\s+rules|you\s+are\s+now\s+dan)\b",
            re.IGNORECASE,
        ),
    ),
]

# Safe endpoints where full payload inspection is skipped (e.g. static docs, swagger)
EXCLUDED_PATHS = {"/docs", "/redoc", "/openapi.json", "/favicon.ico"}


def inspect_text(text: str) -> Optional[str]:
    """Inspects a string against all attack signatures."""
    if not text:
        return None
    for attack_type, pattern in ATTACK_PATTERNS:
        if pattern.search(text):
            return attack_type
    return None


class WAFShieldMiddleware(BaseHTTPMiddleware):
    """Deep Packet Inspection Web Application Firewall (WAF) Middleware.
    
    Inspects URL query parameters, headers, and request bodies for hostile payloads.
    Auto-jails attacking IPs with a troll middle-finger response.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        client_ip = get_client_ip(request)

        # Skip docs endpoints and trusted infrastructure / whitelisted IPs
        if path in EXCLUDED_PATHS or is_ip_whitelisted(client_ip):
            return await call_next(request)

        # 1. Inspect URL Path & Query Params
        query_string = str(request.url.query)
        detected_attack = inspect_text(path) or inspect_text(query_string)

        # 2. Inspect Hostile Request Headers
        if not detected_attack:
            for header_name in ["user-agent", "referer", "x-forwarded-for"]:
                header_val = request.headers.get(header_name, "")
                detected_attack = inspect_text(header_val)
                if detected_attack:
                    break

        # 3. Inspect Body for Non-File Upload Requests
        content_type = request.headers.get("content-type", "")
        if not detected_attack and "multipart/form-data" not in content_type:
            try:
                body_bytes = await request.body()
                # Replay body for downstream handlers
                async def receive():
                    return {"type": "http.request", "body": body_bytes}
                request._receive = receive

                if body_bytes and len(body_bytes) < 100000:  # Max 100KB inspected
                    body_text = body_bytes.decode("utf-8", errors="ignore")
                    detected_attack = inspect_text(body_text)
            except Exception as e:
                logger.error(f"Error reading body for WAF inspection: {e}")

        # If an attack signature was detected, jail the IP and reject
        if detected_attack:
            request_id = getattr(request.state, "request_id", "req_blocked")
            logger.critical(
                f"🚨 [WAF ATTACK TRAPPED] Type: {detected_attack} | IP: {client_ip} | Path: {path}"
            )
            # High severity attacks trigger instant 24h ban
            await ban_ip_immediately(
                client_ip=client_ip,
                reason=f"WAF Shield Detected {detected_attack} attack on {path}",
            )

            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "data": None,
                    "warning": "🖕 ACCESS DENIED! ATTACK DETECTED & IP AUTO-JAILED.",
                    "error": {
                        "code": "ATTACK_PAYLOAD_DETECTED",
                        "message": f"Malicious attack payload detected ({detected_attack}). Your IP has been jailed for 24 hours.",
                    },
                    "request_id": request_id,
                },
            )

        return await call_next(request)

