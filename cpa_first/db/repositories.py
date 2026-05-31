"""데이터 접근 함수 — 전부 user_id로 스코핑 (IDOR 방지).

핸들러는 절대 raw SQL을 만들지 않고 이 함수들만 호출. 모든 쿼리는 파라미터 바인딩.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from cpa_first.db.models import (
    AttemptDiagnosis,
    MistakeLog,
    Prescription,
    RefreshToken,
    ReviewOverride,
    User,
    UserState,
)

# ───────────────────────── Users ─────────────────────────


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def count_users(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User)) or 0


def create_user(db: Session, *, email: str, password_hash: str, role: str = "user") -> User:
    user = User(email=normalize_email(email), password_hash=password_hash, role=role)
    db.add(user)
    db.flush()
    return user


# ───────────────────────── Refresh tokens ─────────────────────────


def create_refresh_token(
    db: Session, *, user_id: uuid.UUID, token_hash: str, expires_at: datetime
) -> RefreshToken:
    rt = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(rt)
    db.flush()
    return rt


def get_refresh_token_by_hash(db: Session, token_hash: str) -> RefreshToken | None:
    """revoked/expired 여부와 무관하게 해시로 조회 (재사용 탐지용)."""
    return db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))


def get_active_refresh_token(db: Session, token_hash: str) -> RefreshToken | None:
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if rt is None or rt.revoked_at is not None:
        return None
    expires_at = rt.expires_at
    if expires_at.tzinfo is None:  # SQLite는 naive로 반환될 수 있음 → UTC 가정
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        return None
    return rt


def revoke_refresh_token(db: Session, rt: RefreshToken) -> None:
    rt.revoked_at = datetime.now(UTC)
    db.add(rt)
    db.flush()


def revoke_all_user_refresh_tokens(db: Session, user_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    tokens = db.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
    )
    for t in tokens:
        t.revoked_at = now
        db.add(t)
    db.flush()


# ───────────────────────── User state ─────────────────────────


def upsert_user_state(db: Session, *, user_id: uuid.UUID, state: dict[str, Any]) -> UserState:
    row = db.get(UserState, user_id)
    if row is None:
        row = UserState(user_id=user_id)
        db.add(row)
    row.target_exam = state.get("target_exam", "CPA_1")
    row.days_until_exam = int(state["days_until_exam"])
    row.available_hours_per_day = float(state["available_hours_per_day"])
    row.current_stage = state.get("current_stage")
    row.subject_states = state.get("subject_states", [])
    db.flush()
    return row


def get_user_state(db: Session, user_id: uuid.UUID) -> UserState | None:
    return db.get(UserState, user_id)


# ───────────────────────── Prescriptions ─────────────────────────


def save_prescription(
    db: Session, *, user_id: uuid.UUID, prescription: dict[str, Any]
) -> Prescription:
    """이전 active를 끄고 새 처방을 active로 저장 (멱등 upsert).

    prescription_id는 prescribe()가 (user_id, 입력)으로 결정적 생성하므로 동일 입력
    재진단은 같은 id가 된다 → INSERT면 PK 충돌(500). 기존 행이 있으면 갱신해 멱등 보장.
    """
    db.execute(
        update(Prescription)
        .where(Prescription.user_id == user_id, Prescription.is_active.is_(True))
        .values(is_active=False)
    )
    pid = prescription.get("prescription_id") or f"rx-{user_id}-{uuid.uuid4().hex[:12]}"
    existing = db.get(Prescription, pid)
    if existing is not None and existing.user_id == user_id:
        existing.payload = prescription
        existing.generated_at = datetime.now(UTC)
        existing.is_active = True
        db.flush()
        return existing
    if existing is not None:
        # 다른 사용자의 동일 id(이론상 불가 — pid에 user_id 포함). 충돌 회피용 새 id.
        pid = f"rx-{user_id}-{uuid.uuid4().hex[:12]}"
    row = Prescription(
        id=pid,
        user_id=user_id,
        payload=prescription,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def get_active_prescription(db: Session, user_id: uuid.UUID) -> Prescription | None:
    return db.scalar(
        select(Prescription)
        .where(Prescription.user_id == user_id, Prescription.is_active.is_(True))
        .order_by(Prescription.generated_at.desc())
        .limit(1)
    )


# ───────────────────────── Mistake logs ─────────────────────────


def add_mistake_log(db: Session, *, user_id: uuid.UUID, log: dict[str, Any]) -> bool:
    """멱등 삽입. 이미 (user_id, log_id) 존재하면 False, 신규면 True."""
    existing = db.get(MistakeLog, (user_id, log["log_id"]))
    if existing is not None:
        return False
    row = MistakeLog(
        user_id=user_id,
        log_id=log["log_id"],
        problem_id=log["problem_id"],
        attempt_at=log["attempt_at"],
        correct=bool(log["correct"]),
        time_seconds=int(log["time_seconds"]),
        skipped=log.get("skipped"),
        mistake_categories=log.get("mistake_categories", []),
        self_note=log.get("self_note"),
        session_id=log.get("session_id"),
    )
    db.add(row)
    db.flush()
    return True


def list_mistake_logs(db: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(MistakeLog)
        .where(MistakeLog.user_id == user_id)
        .order_by(MistakeLog.created_at.asc())
    )
    return [_mistake_log_to_dict(r) for r in rows]


def count_mistake_logs(db: Session, user_id: uuid.UUID) -> int:
    return (
        db.scalar(select(func.count()).select_from(MistakeLog).where(MistakeLog.user_id == user_id))
        or 0
    )


def delete_mistake_logs(db: Session, user_id: uuid.UUID) -> None:
    db.execute(delete(MistakeLog).where(MistakeLog.user_id == user_id))
    db.flush()


def _mistake_log_to_dict(r: MistakeLog) -> dict[str, Any]:
    return {
        "log_id": r.log_id,
        "user_id": str(r.user_id),
        "problem_id": r.problem_id,
        "attempt_at": r.attempt_at,
        "correct": r.correct,
        "time_seconds": r.time_seconds,
        "skipped": r.skipped,
        "mistake_categories": list(r.mistake_categories or []),
        "self_note": r.self_note,
        "session_id": r.session_id,
    }


# ───────────────────────── Attempt diagnoses ─────────────────────────


def add_attempt_diagnosis(
    db: Session,
    *,
    user_id: uuid.UUID,
    question_id: str,
    selected_choice: int,
    time_seconds: int | None,
    time_limit_seconds: int,
    diagnosis: dict[str, Any],
) -> dict[str, Any]:
    # attempt_id는 항상 서버에서 생성(uuid). 클라이언트 지정 불가 →
    # 타 사용자 PK 충돌 존재 오라클 / 위조 차단.
    row = AttemptDiagnosis(
        user_id=user_id,
        question_id=question_id,
        selected_choice=selected_choice,
        time_seconds=time_seconds,
        time_limit_seconds=time_limit_seconds,
        diagnosis=diagnosis,
    )
    db.add(row)
    db.flush()
    return _attempt_to_dict(row)


def list_attempt_diagnoses(db: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(AttemptDiagnosis)
        .where(AttemptDiagnosis.user_id == user_id)
        .order_by(AttemptDiagnosis.created_at.asc())
    )
    return [_attempt_to_dict(r) for r in rows]


def delete_attempt_diagnoses(db: Session, user_id: uuid.UUID) -> None:
    db.execute(delete(AttemptDiagnosis).where(AttemptDiagnosis.user_id == user_id))
    db.flush()


def _attempt_to_dict(r: AttemptDiagnosis) -> dict[str, Any]:
    created = r.created_at.isoformat() if isinstance(r.created_at, datetime) else r.created_at
    return {
        "attempt_id": r.attempt_id,
        "user_id": str(r.user_id),
        "question_id": r.question_id,
        "selected_choice": r.selected_choice,
        "time_seconds": r.time_seconds,
        "time_limit_seconds": r.time_limit_seconds,
        "created_at": created,
        "diagnosis": r.diagnosis,
    }


# ───────────────────────── Review overrides ─────────────────────────


def get_review_override(db: Session, ref_type: str, ref_id: str) -> ReviewOverride | None:
    return db.get(ReviewOverride, (ref_type, ref_id))


def all_review_overrides(db: Session) -> dict[tuple[str, str], str]:
    rows = db.scalars(select(ReviewOverride))
    return {(r.ref_type, r.ref_id): r.review_status for r in rows}


def upsert_review_override(
    db: Session, *, ref_type: str, ref_id: str, review_status: str, reviewer: str | None
) -> tuple[str | None, ReviewOverride]:
    """(previous_status, row) 반환."""
    row = db.get(ReviewOverride, (ref_type, ref_id))
    previous = row.review_status if row is not None else None
    if row is None:
        row = ReviewOverride(ref_type=ref_type, ref_id=ref_id)
        db.add(row)
    row.review_status = review_status
    row.reviewer = reviewer
    db.flush()
    return previous, row
