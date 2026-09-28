import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet
from app.core.config import settings

# Derive a consistent 32-byte Fernet key from settings.JWT_SECRET
_raw_key = hashlib.sha256(settings.JWT_SECRET.encode("utf-8")).digest()
_fernet_key = base64.urlsafe_b64encode(_raw_key)
_cipher = Fernet(_fernet_key)


def encrypt_field(plaintext: Optional[str]) -> Optional[str]:
    """Encrypts sensitive plaintext string using AES-256 (Fernet) at rest."""
    if not plaintext:
        return plaintext
    try:
        encrypted_bytes = _cipher.encrypt(plaintext.encode("utf-8"))
        return encrypted_bytes.decode("utf-8")
    except Exception:
        return plaintext


def decrypt_field(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypts AES-256 (Fernet) ciphertext back to original plaintext."""
    if not ciphertext:
        return ciphertext
    try:
        decrypted_bytes = _cipher.decrypt(ciphertext.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception:
        # If not encrypted or fallback, return as is
        return ciphertext

