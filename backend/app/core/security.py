import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt

from app.core.config import get_settings

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, n_str, r_str, p_str, salt_hex, expected_hex = stored_hash.split("$")
        if scheme != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n_str),
            r=int(r_str),
            p=int(p_str),
            dklen=len(bytes.fromhex(expected_hex)),
        )
        return hmac.compare_digest(derived.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str | UUID,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    expire = now + (
        expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "iss": "isla-institutional-ai",
        "type": "access",
        "jti": secrets.token_hex(16),
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        issuer="isla-institutional-ai",
        options={"require": ["sub", "exp", "iat"]},
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Tipo de token inválido.")
    return payload
