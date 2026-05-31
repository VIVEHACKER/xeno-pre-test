"""레이트 리미터 (slowapi). 로그인 5/분, API 기본 100/분.

키: 프록시 뒤(PaaS)이므로 X-Forwarded-For 첫 홉 우선, 없으면 client host.
create_app()이 settings로 limiter.enabled를 권위적으로 재설정 (테스트는 비활성).
"""

from __future__ import annotations

from slowapi import Limiter
from starlette.requests import Request

from cpa_first.config import get_settings


def client_ip(request: Request) -> str:
    """레이트리밋 키. XFF 좌측은 클라이언트가 위조 가능하므로 신뢰하지 않는다.

    PaaS LB는 실제 클라이언트 IP를 X-Forwarded-For의 우측에 덧붙인다. trusted_proxy_hops
    만큼 우측에서 들어간 항목을 실제 클라이언트로 본다(좌측 위조값은 무시 → 우회 차단).
    hops=0 또는 XFF 없음이면 직접 peer(request.client.host) 사용.
    """
    hops = get_settings().trusted_proxy_hops
    if hops > 0:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            parts = [p.strip() for p in fwd.split(",") if p.strip()]
            if parts:
                return parts[-min(hops, len(parts))]
    return request.client.host if request.client else "anonymous"


def login_rate_limit() -> str:
    return get_settings().rate_limit_login


def register_rate_limit() -> str:
    return get_settings().rate_limit_register


def refresh_rate_limit() -> str:
    return get_settings().rate_limit_refresh


_settings = get_settings()
limiter = Limiter(
    key_func=client_ip,
    default_limits=[_settings.rate_limit_default],
    enabled=_settings.rate_limit_enabled,
    headers_enabled=True,
)
