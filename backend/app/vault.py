"""Cloud credentials are encrypted at rest with Fernet. They are never returned by the API or logged."""
import json
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from .config import get_settings


def _fernet() -> Fernet:
    key = get_settings().secrets_key
    if not key:
        raise HTTPException(422, 'SECRETS_KEY is not configured on the server, so credentials cannot be stored. Run scripts/setup.py or set SECRETS_KEY in .env.')
    try:
        return Fernet(key.encode())
    except ValueError:
        raise HTTPException(500, 'SECRETS_KEY is not a valid Fernet key.')


def seal(credentials: dict) -> str:
    return _fernet().encrypt(json.dumps(credentials, separators=(',', ':')).encode()).decode()


def unseal(token: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken:
        raise HTTPException(500, 'Stored credentials cannot be decrypted. SECRETS_KEY may have changed; re-enter the credentials.')


def redact(text: str, credentials: dict | None) -> str:
    """Remove any credential value from an error message before it is stored or shown."""
    for value in (credentials or {}).values():
        if isinstance(value, str) and len(value) >= 6:
            text = text.replace(value, '***')
    return text
