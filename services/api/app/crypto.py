"""Field- and file-level encryption (AES-256-GCM) on top of storage/disk encryption."""
import base64, hashlib, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import TypeDecorator, Text
from .config import get_settings

_PREFIX = b"v1:"


def _key() -> bytes:
    s = get_settings()
    if s.data_encryption_key:
        k = base64.b64decode(s.data_encryption_key)
        if len(k) != 32:
            raise RuntimeError("DATA_ENCRYPTION_KEY must decode to 32 bytes")
        return k
    # Development only: derived key. validate() forbids this in production.
    return hashlib.sha256(("dev-dek:" + s.secret_key).encode()).digest()


def encrypt_bytes(data: bytes, aad: bytes = b"") -> bytes:
    nonce = os.urandom(12)
    return _PREFIX + nonce + AESGCM(_key()).encrypt(nonce, data, aad)


def decrypt_bytes(blob: bytes, aad: bytes = b"") -> bytes:
    if not blob.startswith(_PREFIX):
        raise ValueError("Unknown ciphertext version")
    body = blob[len(_PREFIX):]
    return AESGCM(_key()).decrypt(body[:12], body[12:], aad)


class EncryptedText(TypeDecorator):
    """Transparently encrypts sensitive clinical free text at rest."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return base64.b64encode(encrypt_bytes(str(value).encode())).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return decrypt_bytes(base64.b64decode(value)).decode()
        except Exception:
            return "[unreadable: encryption key mismatch]"
