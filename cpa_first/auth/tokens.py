"""JWT access 토큰 + 불투명 refresh 토큰.

access: HS256 JWT {sub, role, type:'access', iat, exp, jti}.
refresh: secrets.token_urlsafe 랜덤. DB엔 SHA-256 해시만 저장 (평문 비저장).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from cpa_first.config import Settings


class TokenError(Exception):
    """access 토큰 검증 실패 (만료/서명오류/형식오류)."""


@dataclass
class AccessClaims:
    user_id: uuid.UUID
    role: str
    jti: str


def create_access_token(settings: Settings, *, user_id: uuid.UUID, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.jwt_access_ttl_seconds)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("type") != "access":
        raise TokenError("not an access token")
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (ValueError, KeyError) as exc:
        raise TokenError("invalid subject") from exc
    return AccessClaims(
        user_id=user_id, role=str(payload.get("role", "user")), jti=str(payload.get("jti", ""))
    )


@dataclass
class RefreshTokenMaterial:
    plaintext: str
    token_hash: str
    expires_at: datetime


def generate_refresh_token(settings: Settings) -> RefreshTokenMaterial:
    plaintext = secrets.token_urlsafe(48)
    return RefreshTokenMaterial(
        plaintext=plaintext,
        token_hash=hash_refresh_token(plaintext),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.jwt_refresh_ttl_seconds),
    )


def hash_refresh_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
