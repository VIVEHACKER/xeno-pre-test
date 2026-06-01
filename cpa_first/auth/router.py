"""인증 엔드포인트: /auth/register, /login, /refresh, /logout, /me.

refresh 토큰은 HttpOnly+Secure+SameSite 쿠키(path=/auth)로만 오간다.
access 토큰은 JSON 응답으로 주고 SPA는 메모리에만 보관.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from cpa_first.auth import passwords, tokens
from cpa_first.auth.dependencies import get_current_user
from cpa_first.config import Settings, get_settings
from cpa_first.db import repositories as repo
from cpa_first.db.models import User
from cpa_first.db.session import get_db
from cpa_first.ratelimit import (
    limiter,
    login_rate_limit,
    refresh_rate_limit,
    register_rate_limit,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# 더미 해시: 미존재 사용자 로그인 시에도 verify를 돌려 타이밍 차이로 인한 계정 열거 방지.
_DUMMY_HASH = passwords.hash_password("dummy-timing-equalizer")


class RegisterRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v) or len(v) > 320:
            raise ValueError("invalid email")
        return v

    @field_validator("password")
    @classmethod
    def _valid_password(cls, v: str) -> str:
        if not 8 <= len(v) <= 128:
            raise ValueError("password must be 8-128 characters")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


def _user_out(user: User) -> UserOut:
    return UserOut(id=str(user.id), email=user.email, role=user.role)


def _set_refresh_cookie(response: Response, settings: Settings, plaintext: str) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=plaintext,
        max_age=settings.jwt_refresh_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/auth",
        domain=settings.cookie_domain,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path="/auth",
        domain=settings.cookie_domain,
    )


def _issue_session(
    db: Session, response: Response, settings: Settings, user: User
) -> TokenResponse:
    """access 발급 + 새 refresh 토큰 생성/저장 + 쿠키 세팅."""
    access = tokens.create_access_token(settings, user_id=user.id, role=user.role)
    material = tokens.generate_refresh_token(settings)
    repo.create_refresh_token(
        db, user_id=user.id, token_hash=material.token_hash, expires_at=material.expires_at
    )
    _set_refresh_cookie(response, settings, material.plaintext)
    return TokenResponse(
        access_token=access,
        expires_in=settings.jwt_access_ttl_seconds,
        user=_user_out(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(register_rate_limit)
def register(
    request: Request,  # slowapi 레이트리밋 키 추출에 필요
    payload: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    if repo.get_user_by_email(db, payload.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")
    role = "user"
    if settings.bootstrap_first_user_admin and repo.count_users(db) == 0:
        role = "admin"
    user = repo.create_user(
        db, email=payload.email, password_hash=passwords.hash_password(payload.password), role=role
    )
    result = _issue_session(db, response, settings, user)
    db.commit()
    return result


@router.post("/login", response_model=TokenResponse)
@limiter.limit(login_rate_limit)
def login(
    request: Request,  # slowapi 레이트리밋에 필요
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = repo.get_user_by_email(db, payload.email)
    if user is None:
        passwords.verify_password(_DUMMY_HASH, payload.password)  # 타이밍 평준화
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    if not passwords.verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(payload.password)
        db.add(user)
    result = _issue_session(db, response, settings, user)
    db.commit()
    return result


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(refresh_rate_limit)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    raw = request.cookies.get(settings.refresh_cookie_name)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no refresh token")
    token_hash = tokens.hash_refresh_token(raw)
    rt = repo.get_active_refresh_token(db, token_hash)
    if rt is None:
        # 재사용 탐지 (OAuth 2.0 BCP / RFC 9700): 토큰 행은 존재하나 이미 폐기됐다면,
        # 회전된 토큰의 재제시 = 탈취 정황 → 해당 사용자의 모든 refresh 토큰 폐기.
        stale = repo.get_refresh_token_by_hash(db, token_hash)
        if stale is not None and stale.revoked_at is not None:
            repo.revoke_all_user_refresh_tokens(db, stale.user_id)
            db.commit()
        _clear_refresh_cookie(response, settings)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired refresh token"
        )
    user = repo.get_user_by_id(db, rt.user_id)
    if user is None:
        _clear_refresh_cookie(response, settings)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    # 회전: 이전 refresh 폐기 후 새 세션 발급.
    repo.revoke_refresh_token(db, rt)
    result = _issue_session(db, response, settings, user)
    db.commit()
    return result


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    raw = request.cookies.get(settings.refresh_cookie_name)
    if raw:
        rt = repo.get_active_refresh_token(db, tokens.hash_refresh_token(raw))
        if rt is not None:
            repo.revoke_refresh_token(db, rt)
            db.commit()
    _clear_refresh_cookie(response, settings)
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)
