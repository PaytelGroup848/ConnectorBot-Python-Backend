import time
from typing import Optional
from fastapi import Request
from app.core.redis import cache_service
from app.core.exceptions import RateLimitException
from app.middleware.security_jail import get_client_ip, is_ip_whitelisted


class RateLimiter:
    """Multi-tiered rate limiter for IP, User, Tenant, and sensitive endpoints."""
    def __init__(self, requests_per_minute: int = 60, tier_prefix: str = "general"):
        self.requests_per_minute = requests_per_minute
        self.tier_prefix = tier_prefix

    async def __call__(self, request: Request):
        client_ip = get_client_ip(request)
        user_id = getattr(request.state, "user_id", None)
        tenant_id = getattr(request.state, "tenant_id", None)

        # Build rate limit identifiers
        ip_key = f"rate:{self.tier_prefix}:ip:{client_ip}"
        now_bucket = int(time.time() // 60)

        # Trusted infrastructure & whitelisted IPs bypass IP bucket rate limits
        if not is_ip_whitelisted(client_ip):
            current_ip_count = await cache_service.client.incr(f"{ip_key}:{now_bucket}")
            if current_ip_count == 1:
                await cache_service.client.expire(f"{ip_key}:{now_bucket}", 65)

            if current_ip_count > self.requests_per_minute:
                raise RateLimitException(f"Too many requests from this IP. Limit is {self.requests_per_minute}/min.")

        # If authenticated, enforce user-level limit
        if user_id:
            user_key = f"rate:{self.tier_prefix}:usr:{user_id}"
            current_user_count = await cache_service.client.incr(f"{user_key}:{now_bucket}")
            if current_user_count == 1:
                await cache_service.client.expire(f"{user_key}:{now_bucket}", 65)

            if current_user_count > self.requests_per_minute:
                raise RateLimitException("User request quota exceeded. Please slow down.")


# Predefined rate limiters for common endpoints
standard_limiter = RateLimiter(requests_per_minute=120, tier_prefix="std")
chat_limiter = RateLimiter(requests_per_minute=30, tier_prefix="chat")
ticket_limiter = RateLimiter(requests_per_minute=15, tier_prefix="ticket")
admin_limiter = RateLimiter(requests_per_minute=60, tier_prefix="admin")
voice_limiter = RateLimiter(requests_per_minute=20, tier_prefix="voice")

