from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict
import re
from jose import jwt, JWTError
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Sensitive patterns to redact in logs/prompts
SENSITIVE_PATTERNS = [
    r'(?i)(bearer\s+)[a-zA-Z0-9_\-\.]+',
    r'(?i)(api[_-]?key["\']?\s*[:=]\s*["\']?)[a-zA-Z0-9_\-]+',
    r'(?i)(password["\']?\s*[:=]\s*["\']?)[^"\'\s]+',
    r'(?i)(jwt["\']?\s*[:=]\s*["\']?)[a-zA-Z0-9_\-\.]+',
]


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(
    subject: str,
    tenant_id: str,
    role: str = "USER",
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {
        "sub": subject,
        "tenant_id": tenant_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if extra_claims:
        to_encode.update(extra_claims)

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError:
        return None


def sanitize_sensitive_data(text: str) -> str:
    """Redacts secrets, API keys, passwords and tokens from string before logging or sending to models."""
    if not isinstance(text, str):
        return text
    sanitized = text
    for pattern in SENSITIVE_PATTERNS:
        sanitized = re.sub(pattern, r'\1[REDACTED]', sanitized)
    return sanitized

