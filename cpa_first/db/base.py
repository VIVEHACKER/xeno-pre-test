"""SQLAlchemy DeclarativeBase + 공통 헬퍼."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


def utcnow() -> datetime:
    """tz-aware UTC now. Python-side default (서버 비의존, SQLite/PG 동일)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass
