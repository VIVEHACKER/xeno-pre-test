"""DB 엔진 / 세션 팩토리 / FastAPI 의존성.

- prod: Postgres(psycopg) + QueuePool (pool_size/max_overflow/pre_ping)
- test/dev: SQLite. in-memory는 StaticPool로 스레드 간 단일 커넥션 공유
  (FastAPI 동기 핸들러가 스레드풀에서 도므로 check_same_thread=False 필요).
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cpa_first.config import Settings
from cpa_first.db.base import Base


def _is_memory_sqlite(url: str) -> bool:
    return url.startswith("sqlite") and (
        ":memory:" in url or url in ("sqlite://", "sqlite+pysqlite://")
    )


def _ensure_sqlite_parent(url: str) -> None:
    """file sqlite의 부모 디렉터리 생성 (dev 편의: data/runtime/ 미존재 시)."""
    # sqlite+pysqlite:///./data/runtime/x.sqlite3 → 파일 경로 추출
    prefix_split = url.split(":///", 1)
    if len(prefix_split) != 2:
        return
    path_part = prefix_split[1]
    if not path_part or path_part == ":memory:":
        return
    from pathlib import Path

    Path(path_part).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def make_engine(settings: Settings) -> Engine:
    url = settings.database_url
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        if _is_memory_sqlite(url):
            return create_engine(url, connect_args=connect_args, poolclass=StaticPool, future=True)
        _ensure_sqlite_parent(url)
        return create_engine(url, connect_args=connect_args, future=True)
    return create_engine(
        url,
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        future=True,
    )


class Database:
    """엔진 + 세션 팩토리 보유자. app.state.db에 1개 저장."""

    def __init__(self, settings: Settings, engine: Engine | None = None) -> None:
        self.settings = settings
        self.engine: Engine = engine if engine is not None else make_engine(settings)
        self.session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, class_=Session
        )

    def create_all(self) -> None:
        """metadata로 스키마 생성. SQLite(dev/test) 편의용. prod는 Alembic."""
        # 모델이 메타데이터에 등록되도록 import.
        from cpa_first.db import models  # noqa: F401

        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()

    def healthcheck(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False


def get_db(request: Request) -> Iterator[Session]:
    """요청 단위 세션. 예외 시 rollback, 항상 close. commit은 핸들러/리포지토리에서."""
    db: Database = request.app.state.db
    session = db.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
