"""중앙 설정 — 모든 런타임 구성을 환경변수에서 소싱한다 (pydantic-settings).

원칙 (backend/security 규칙):
- 하드코딩 금지. DB URL / 시크릿 / CORS / 토큰 TTL은 전부 env.
- 프로덕션에서 필수값 누락/위험 기본값이면 부팅 시 fail-fast.
- `.env`는 dev 편의용으로만 로드 (prod는 PaaS 시크릿 매니저 주입).
"""

from __future__ import annotations

import sys
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# prod에서 거부되는, 명백히 안전하지 않은 dev 기본값.
DEV_INSECURE_JWT_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["dev", "staging", "prod", "test"] = "dev"

    # --- Database ---
    # 기본값은 로컬/테스트용 SQLite. 프로덕션은 postgresql+psycopg://... 주입.
    database_url: str = "sqlite+pysqlite:///./data/runtime/cpa_dev.sqlite3"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True

    # --- Auth / JWT ---
    jwt_secret: str = DEV_INSECURE_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_seconds: int = 15 * 60  # access 15분
    jwt_refresh_ttl_seconds: int = 7 * 24 * 60 * 60  # refresh 7일
    # 첫 가입 사용자를 admin으로 승격할지 (부트스트랩). prod 기본 false.
    bootstrap_first_user_admin: bool = False

    # --- Cookies (refresh token 전달) ---
    cookie_secure: bool = True
    cookie_samesite: Literal["strict", "lax", "none"] = "strict"
    cookie_domain: str | None = None
    refresh_cookie_name: str = "cpa_refresh"

    # --- CORS (콤마 구분 문자열 → 리스트) ---
    cors_origins: str = ""

    # --- Rate limits (slowapi 문법) ---
    rate_limit_default: str = "100/minute"
    rate_limit_login: str = "5/minute"
    rate_limit_register: str = "5/minute"
    rate_limit_refresh: str = "20/minute"
    rate_limit_enabled: bool = True
    # 레이트리밋 키 산정 시 신뢰하는 프록시 홉 수 (PaaS LB 앞단). X-Forwarded-For의
    # 우측에서 이 수만큼 들어간 항목을 실제 클라이언트로 본다. 0이면 XFF 무시(직접 peer).
    # 공격자가 XFF를 위조해도 좌측 위조값은 무시되어 레이트리밋 우회 불가.
    trusted_proxy_hops: int = 1

    # --- Logging / Observability ---
    log_level: str = "INFO"
    log_json: bool = True
    sentry_dsn: str | None = None
    metrics_enabled: bool = True

    # --- Knowledge base / solver ---
    seed_dir: str | None = None  # None이면 패키지 기본 위치
    anthropic_api_key: str | None = None
    cpa_solver_mode: str = "reasoned"

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}:
            raise ValueError(f"invalid log_level: {v}")
        return v

    @field_validator("database_url")
    @classmethod
    def _normalize_db_scheme(cls, v: str) -> str:
        """관리형 PaaS가 주는 bare postgres:// / postgresql:// → psycopg v3 dialect.

        앱·alembic env.py·Fly release_command(엔트리포인트 우회) 모두 동일하게 교정되어
        psycopg2(미설치) dialect 로딩 실패를 막는다.
        """
        for prefix in ("postgres://", "postgresql://", "postgresql+psycopg2://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix) :]
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.environment in ("prod", "staging")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @model_validator(mode="after")
    def _fail_fast_in_prod(self) -> Settings:
        if self.is_prod:
            problems: list[str] = []
            if self.jwt_secret == DEV_INSECURE_JWT_SECRET or len(self.jwt_secret) < 32:
                problems.append("JWT_SECRET must be set to a strong (>=32 char) value")
            if self.is_sqlite:
                problems.append("DATABASE_URL must be a managed Postgres URL in production")
            if "*" in self.cors_origins:
                problems.append("CORS_ORIGINS must be an explicit allowlist (no '*') in production")
            if not self.cors_origin_list:
                problems.append("CORS_ORIGINS must list the frontend origin(s) in production")
            if self.cookie_secure is False:
                problems.append("COOKIE_SECURE must be true in production")
            if problems:
                raise ValueError(
                    "Invalid production configuration:\n  - " + "\n  - ".join(problems)
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """프로세스 단위 싱글톤. 부팅 시 1회 검증."""
    try:
        return Settings()
    except Exception as exc:  # 설정 오류는 부팅 즉시 중단
        print(f"[config] FATAL: invalid settings: {exc}", file=sys.stderr)
        raise


def reset_settings_cache() -> None:
    """테스트에서 환경변수 변경 후 캐시 무효화."""
    get_settings.cache_clear()
