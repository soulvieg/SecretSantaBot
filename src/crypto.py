import json
from typing import Any

from cryptography.fernet import Fernet

from config import get_settings

_cipher: Fernet | None = None

def _fernet() -> Fernet:
    global _cipher
    if _cipher is None:
        key =  get_settings().encryption_key
        if not key:
            raise RuntimeError("ENCRYPTION_KEY is missing in .env")
        _cipher = Fernet(key.encode())
    return _cipher

def encrypt_payload(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()

def decrypt_payload(token: str) -> dict[str, Any]:
    return json.loads(_fernet().decrypt(token.encode()))
