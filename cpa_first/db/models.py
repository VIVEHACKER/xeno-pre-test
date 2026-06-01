"""ORM 모델 — per-user 런타임 상태 + 인증.

파일 기반(data/runtime/*.json|*.jsonl) 전역 단일 사용자 상태를 대체한다.
모든 사용자 데이터는 user_id로 스코핑. user_id는 JWT subject에서만 주입(바디 금지).
이식 가능 타입만 사용: Uuid(PG=UUID, SQLite=CHAR32), JSON, String, DateTime(tz).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON as SA_JSON,
)
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cpa_first.db.base import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 이메일은 앱에서 lowercase 정규화 후 저장 → unique로 대소문자 무시 효과.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """refresh 토큰 해시 저장. 회전 시 이전 토큰 revoke. 평문 토큰은 저장하지 않음."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class UserState(Base):
    """사용자별 최신 진단 입력 상태. user당 1행 (upsert)."""

    __tablename__ = "user_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    target_exam: Mapped[str] = mapped_column(String(32), nullable=False, default="CPA_1")
    days_until_exam: Mapped[int] = mapped_column(Integer, nullable=False)
    available_hours_per_day: Mapped[float] = mapped_column(Float, nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject_states: Mapped[list] = mapped_column(SA_JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Prescription(Base):
    """사용자별 처방. 최신 1건이 is_active=True. 이력 누적."""

    __tablename__ = "prescriptions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # prescription_id
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    payload: Mapped[dict] = mapped_column(SA_JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MistakeLog(Base):
    """오답/풀이 로그. (user_id, log_id) 복합 PK로 멱등 보장."""

    __tablename__ = "mistake_logs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    log_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    problem_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    attempt_at: Mapped[str] = mapped_column(String(64), nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    time_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mistake_categories: Mapped[list] = mapped_column(SA_JSON, nullable=False, default=list)
    self_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class AttemptDiagnosis(Base):
    """풀이맵 기반 응시 진단 기록."""

    __tablename__ = "attempt_diagnoses"

    attempt_id: Mapped[str] = mapped_column(
        String(128), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_id: Mapped[str] = mapped_column(String(128), nullable=False)
    selected_choice: Mapped[int] = mapped_column(Integer, nullable=False)
    time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_limit_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    diagnosis: Mapped[dict] = mapped_column(SA_JSON, nullable=False)


class ReviewOverride(Base):
    """KB 시드의 review_status 오버레이. 시드 파일은 런타임에 절대 쓰지 않음.

    효과적 상태 = override 있으면 override, 없으면 시드의 review_status.
    """

    __tablename__ = "review_overrides"

    ref_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    ref_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    review_status: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
