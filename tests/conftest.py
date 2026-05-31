"""공유 테스트 픽스처.

테스트 세션 전체를 in-memory SQLite + 안전한 테스트 설정으로 고정한다.
conftest는 test 모듈/ cpa_first.api.main import 전에 로드되므로,
module-level `app = create_app()`도 테스트 설정을 사용한다.
"""

from __future__ import annotations

import os

# ── 테스트 환경 고정 (import side-effect: 가장 먼저 실행) ──
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite://")  # in-memory (StaticPool)
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789-0123456789")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from cpa_first.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()


@pytest.fixture
def app():
    """함수 단위로 새 in-memory DB를 가진 앱 인스턴스."""
    from cpa_first.api.main import create_app

    return create_app(settings=get_settings())


def register(client: TestClient, email: str, password: str = "supersecret1") -> dict:
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def anon_client(app) -> TestClient:
    """인증 헤더 없는 클라이언트 (401/공개 엔드포인트 테스트용)."""
    return TestClient(app)


@pytest.fixture
def client(app) -> TestClient:
    """일반 사용자로 인증된 클라이언트. c.user_id / c.access_token 노출."""
    c = TestClient(app)
    body = register(c, "user@test.com")
    c.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    c.user_id = body["user"]["id"]  # type: ignore[attr-defined]
    c.access_token = body["access_token"]  # type: ignore[attr-defined]
    return c


@pytest.fixture
def admin_client(app) -> TestClient:
    """admin으로 승격된 인증 클라이언트 (검수 엔드포인트용)."""
    from cpa_first.db import repositories as repo

    c = TestClient(app)
    body = register(c, "admin@test.com")
    db = app.state.db.session_factory()
    try:
        user = repo.get_user_by_email(db, "admin@test.com")
        user.role = "admin"
        db.add(user)
        db.commit()
    finally:
        db.close()
    c.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    c.user_id = body["user"]["id"]  # type: ignore[attr-defined]
    return c
