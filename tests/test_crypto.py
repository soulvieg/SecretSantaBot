import pytest
from cryptography.fernet import InvalidToken

import crypto


def test_roundtrip_nested_payload():
    payload = {
        "address": "Via Roma 1",
        "city": "Torino",
        "zip": "10121",
        "digital": {"platform": "steam", "id": "12345"},
        "notes": "citofono rotto — suonare al 3",
    }

    token = crypto.encrypt_payload(payload)

    assert isinstance(token, str)
    assert "Torino" not in token
    assert crypto.decrypt_payload(token) == payload


def test_encrypting_twice_gives_different_tokens():
    payload = {"address": "Via Roma 1"}

    first = crypto.encrypt_payload(payload)
    second = crypto.encrypt_payload(payload)

    # Fernet picks a fresh IV every time: equal plaintext, different token.
    assert first != second
    assert crypto.decrypt_payload(first) == crypto.decrypt_payload(second)


def test_decrypt_with_another_key_fails(monkeypatch):
    token = crypto.encrypt_payload({"address": "Via Roma 1"})
    other_key = "jfSWgqmz8jwGP4G2A3jgz9B4gg1iMXrv0zN4iyeC4Ag="

    monkeypatch.setenv("ENCRYPTION_KEY", other_key)
    monkeypatch.setattr(crypto, "_cipher", None)
    try:
        with pytest.raises(InvalidToken):
            crypto.decrypt_payload(token)
    finally:
        # Restore the shared cipher so the next test reads the conftest key.
        monkeypatch.undo()
        crypto._cipher = None
