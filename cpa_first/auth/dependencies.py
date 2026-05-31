"""FastAPI 인증 의존성. access 토큰 → User. user_id는 여기서만 나온다."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from cpa_first.auth.tokens import TokenError, decode_access_token
from cpa_first.config import Settings, get_settings
from cpa_first.db.models import User
from cpa_first.db.repositories import get_user_by_id
from cpa_first.db.session import get_db

# auto_error=False → 토큰 없을 때 직접 401 처리 (optional 변형 지원).
_bearer = HTTPBearer(auto_error=False)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="authentication required",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if creds is None or not creds.credentials:
        raise _UNAUTHENTICATED
    try:
        claims = decode_access_token(settings, creds.credentials)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user = get_user_by_id(db, claims.user_id)
    if user is None:
        raise _UNAUTHENTICATED
    return user


def get_current_user_optional(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | None:
    if creds is None or not creds.credentials:
        return None
    try:
        claims = decode_access_token(settings, creds.credentials)
    except TokenError:
        return None
    return get_user_by_id(db, claims.user_id)


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin privilege required"
        )
    return user
