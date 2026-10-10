"""Password hashing (scrypt), JWT access tokens and API-key generation/verification.

* Passwords: hashlib.scrypt (n=2**14, r=8, p=1) with a 16-byte random salt, constant-time compare.
* API keys: ``dsk_<prefix>_<secret>``. Only an HMAC-SHA256 of the full key (keyed with SECRET_KEY)
  is stored; the secret is shown once at creation and cannot be recovered.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import get_settings

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, dk_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


def create_access_token(user_id: int, workspace_id: int, role: str, ttl_minutes: int | None = None) -> tuple[str, datetime]:
    settings = get_settings()
    exp = datetime.now(UTC) + timedelta(minutes=ttl_minutes or settings.access_token_ttl_minutes)
    payload = {"sub": str(user_id), "ws": workspace_id, "role": role, "exp": exp, "iat": datetime.now(UTC), "typ": "access"}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256"), exp


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"], options={"require": ["exp", "sub"]})


def generate_api_key() -> tuple[str, str]:
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    return f"dsk_{prefix}_{secret}", prefix


def hash_api_key(key: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), key.encode(), hashlib.sha256).hexdigest()


def parse_api_key(key: str) -> str | None:
    parts = key.split("_", 2)
    if len(parts) != 3 or parts[0] != "dsk" or len(parts[1]) != 8:
        return None
    return parts[1]
