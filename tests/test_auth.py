"""인증 엔드포인트 테스트: register/login/refresh/logout/me + 레이트리밋."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

GOOD_PW = "supersecret1"


def test_register_login_me_flow(anon_client: TestClient):
    r = anon_client.post("/auth/register", json={"email": "a@b.com", "password": GOOD_PW})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["email"] == "a@b.com"
    assert body["user"]["role"] == "user"
    assert body["token_type"] == "bearer"
    token = body["access_token"]

    me = anon_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "a@b.com"


def test_me_requires_token(anon_client: TestClient):
    assert anon_client.get("/auth/me").status_code == 401


def test_me_rejects_garbage_token(anon_client: TestClient):
    r = anon_client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_email_normalized_and_duplicate_rejected(anon_client: TestClient):
    assert (
        anon_client.post(
            "/auth/register", json={"email": "MiXeD@Case.COM", "password": GOOD_PW}
        ).status_code
        == 201
    )
    # 같은 이메일 다른 케이스 → 중복(409)
    dup = anon_client.post("/auth/register", json={"email": "mixed@case.com", "password": GOOD_PW})
    assert dup.status_code == 409
    # 정규화된 이메일로 로그인 가능
    assert (
        anon_client.post(
            "/auth/login", json={"email": "mixed@case.com", "password": GOOD_PW}
        ).status_code
        == 200
    )


def test_login_bad_password(anon_client: TestClient):
    anon_client.post("/auth/register", json={"email": "u@x.com", "password": GOOD_PW})
    r = anon_client.post("/auth/login", json={"email": "u@x.com", "password": "wrongpassword"})
    assert r.status_code == 401


def test_login_unknown_user(anon_client: TestClient):
    r = anon_client.post("/auth/login", json={"email": "ghost@x.com", "password": GOOD_PW})
    assert r.status_code == 401


def test_weak_password_rejected(anon_client: TestClient):
    assert (
        anon_client.post(
            "/auth/register", json={"email": "w@x.com", "password": "short"}
        ).status_code
        == 422
    )


def test_invalid_email_rejected(anon_client: TestClient):
    assert (
        anon_client.post(
            "/auth/register", json={"email": "not-an-email", "password": GOOD_PW}
        ).status_code
        == 422
    )


def test_refresh_rotates_and_logout_revokes(anon_client: TestClient):
    reg = anon_client.post("/auth/register", json={"email": "r@x.com", "password": GOOD_PW})
    assert reg.status_code == 201
    first_access = reg.json()["access_token"]

    # 쿠키(cpa_refresh)가 클라이언트 jar에 저장됨 → refresh 호출
    refreshed = anon_client.post("/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["access_token"] != first_access  # 회전

    # logout → 이후 refresh 실패 (revoke + 쿠키 제거)
    assert anon_client.post("/auth/logout").status_code == 200
    assert anon_client.post("/auth/refresh").status_code == 401


def test_refresh_without_cookie(anon_client: TestClient):
    # 쿠키 없이 호출 → 401
    assert anon_client.post("/auth/refresh").status_code == 401


def test_refresh_reuse_detection_revokes_family(app):
    """폐기된(회전된) refresh 토큰 재제시 = 탈취 정황 → 사용자의 모든 토큰 폐기."""
    from cpa_first.config import get_settings

    name = get_settings().refresh_cookie_name
    c = TestClient(app)
    c.post("/auth/register", json={"email": "reuse@x.com", "password": GOOD_PW})
    old_cookie = c.cookies.get(name)
    assert old_cookie

    # 회전: old_cookie 폐기, 새 토큰(B) 발급 (jar 갱신)
    assert c.post("/auth/refresh").status_code == 200
    assert c.cookies.get(name) != old_cookie

    # 폐기된 old_cookie 재제시 (별도 클라이언트) → 401 + 패밀리 전체 폐기
    attacker = TestClient(app)
    assert attacker.post("/auth/refresh", cookies={name: old_cookie}).status_code == 401

    # 재사용 탐지로 B까지 폐기됨 → 정상 jar(B)로도 refresh 실패
    assert c.post("/auth/refresh").status_code == 401


def test_register_rate_limited(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_REGISTER", "3/minute")
    from cpa_first.config import get_settings, reset_settings_cache
    from cpa_first.ratelimit import limiter

    reset_settings_cache()
    try:
        from cpa_first.api.main import create_app

        c = TestClient(create_app(settings=get_settings()))
        codes = [
            c.post(
                "/auth/register", json={"email": f"reg{i}@x.com", "password": GOOD_PW}
            ).status_code
            for i in range(6)
        ]
        assert 429 in codes, codes
    finally:
        limiter.enabled = False
        if hasattr(limiter, "reset"):
            limiter.reset()
        reset_settings_cache()


def _fake_request(xff: str | None, client_host: str = "10.0.0.9"):
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (client_host, 1234)})


def test_client_ip_ignores_spoofed_left_xff():
    """신뢰 프록시 1홉(기본): XFF 우측(=LB가 덧붙인 실제 IP)만 사용, 좌측 위조값 무시."""
    from cpa_first.ratelimit import client_ip

    # 공격자가 좌측 값을 바꿔도 키(우측)는 동일 → 레이트리밋 우회 불가
    assert client_ip(_fake_request("9.9.9.9, 203.0.113.7")) == "203.0.113.7"
    assert client_ip(_fake_request("1.2.3.4, 203.0.113.7")) == "203.0.113.7"
    # XFF 없으면 직접 peer
    assert client_ip(_fake_request(None)) == "10.0.0.9"


def test_refresh_rate_limited(monkeypatch: pytest.MonkeyPatch):
    """/auth/refresh도 레이트리밋 대상 (로그인 스로틀 우회 차단)."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_REFRESH", "3/minute")
    from cpa_first.config import get_settings, reset_settings_cache
    from cpa_first.ratelimit import limiter

    reset_settings_cache()
    try:
        from cpa_first.api.main import create_app

        c = TestClient(create_app(settings=get_settings()))
        codes = [c.post("/auth/refresh").status_code for _ in range(6)]
        assert 429 in codes, codes
    finally:
        limiter.enabled = False
        if hasattr(limiter, "reset"):
            limiter.reset()
        reset_settings_cache()


def test_login_rate_limited(monkeypatch: pytest.MonkeyPatch):
    """로그인 5회/분 제한 — 활성화 시 초과 요청은 429."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "3/minute")
    from cpa_first.config import get_settings, reset_settings_cache
    from cpa_first.ratelimit import limiter

    reset_settings_cache()
    try:
        from cpa_first.api.main import create_app

        app = create_app(settings=get_settings())
        c = TestClient(app)
        c.post("/auth/register", json={"email": "rl@x.com", "password": GOOD_PW})
        codes = [
            c.post("/auth/login", json={"email": "rl@x.com", "password": GOOD_PW}).status_code
            for _ in range(6)
        ]
        assert 429 in codes, codes
        assert codes.count(200) <= 3
    finally:
        limiter.enabled = False
        if hasattr(limiter, "reset"):
            limiter.reset()
        reset_settings_cache()
