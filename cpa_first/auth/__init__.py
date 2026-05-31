"""인증 — argon2 비밀번호 해싱 + JWT access/refresh.

- access(15분): JWT(HS256), Authorization: Bearer.
- refresh(7일): 불투명 랜덤 토큰. 평문은 HttpOnly 쿠키로만, DB엔 SHA-256 해시만 저장.
- user_id는 access 토큰 sub에서만 주입 (요청 바디 금지) → IDOR 차단.
"""

from cpa_first.auth.dependencies import (
    get_current_user,
    get_current_user_optional,
    require_admin,
)
from cpa_first.auth.router import router as auth_router

__all__ = [
    "auth_router",
    "get_current_user",
    "get_current_user_optional",
    "require_admin",
]
