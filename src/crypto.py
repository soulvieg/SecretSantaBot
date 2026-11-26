import base64
import json
from typing import Any

from cryptography.fernet import Fernet

from config import get_settings

_cipher: Fernet | None = None

KEY_HELP = (
    "Generate one with: uv run python -c "
    '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


def normalize_key(key: str) -> str:
    """Return a valid Fernet key, adding the base64 padding a copy-paste may drop."""
    key = key.strip()
    if not key:
        raise RuntimeError("ENCRYPTION_KEY is missing in .env")
    if len(key) % 4:
        key += "=" * (-len(key) % 4)
    try:
        raw = base64.urlsafe_b64decode(key)
    except Exception as exc:
        raise RuntimeError(
            f"ENCRYPTION_KEY is not valid base64. {KEY_HELP}"
        ) from exc
    if len(raw) != 32:
        raise RuntimeError(
            f"ENCRYPTION_KEY must decode to 32 bytes, got {len(raw)}. {KEY_HELP}"
        )
    return key


def validate_key() -> None:
    """Fail at startup instead of on the first contact form."""
    normalize_key(get_settings().encryption_key)


def _fernet() -> Fernet:
    global _cipher
    if _cipher is None:
        _cipher = Fernet(normalize_key(get_settings().encryption_key).encode())
    return _cipher


def encrypt_payload(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()


def decrypt_payload(token: str) -> dict[str, Any]:
    return json.loads(_fernet().decrypt(token.encode()))
