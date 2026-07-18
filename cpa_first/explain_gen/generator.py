"""실기출 해설 생성기.

한 문항 = blind solve 1회(+재시도) → 정답키 대조 → 해설 레코드.
배치는 파일 존재 기반 체크포인트로 재개 가능하다(중단 후 같은 명령 재실행 = 이어서).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cpa_first.real_exams import (
    EXPLANATION_SCHEMA,
    STATUS_BACKEND_ERROR,
    STATUS_MISMATCH,
    STATUS_PARSE_FAILED,
    STATUS_VERIFIED,
)

# main.py의 _SOLVER_INPUT_FIELDS와 같은 원칙(블랙리스트 아닌 화이트리스트) —
# 과거 reasoned 정답키 누수 사고 재발 방지. correct_choice는 여기 없다.
SOLVER_INPUT_FIELDS = (
    "question_id",
    "subject",
    "unit",
    "exam",
    "applicable_year",
    "stem",
    "choices",
    "concept_tags",
)


def build_blind_question(question: dict[str, Any]) -> dict[str, Any]:
    """solver에 넘길 blind 사본. 정답키·해설·풀이경로가 구조적으로 빠진다."""
    return {k: question[k] for k in SOLVER_INPUT_FIELDS if k in question}


def generate_explanation(
    question: dict[str, Any],
    solver: Any,
    *,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """문항 1건 해설 생성. 정답 불일치/파싱 실패 시 max_attempts까지 재시도.

    반환 레코드의 status:
    - verified_answer_match : AI 답 == 공식 정답키. 해설 학습자 노출 가능.
    - answer_mismatch       : AI 답 != 정답키. 해설 본문은 보존하되 노출 금지.
    - answer_parse_failed   : ANSWER 줄 파싱 실패(chosen_index=-1). 타임아웃 포함.
    - backend_error         : 모든 시도가 백엔드 예외로 실패.
    """
    blind = build_blind_question(question)
    correct = question["correct_choice"]

    started = time.perf_counter()
    chosen = -1
    walkthrough = ""
    model = None
    status = STATUS_BACKEND_ERROR
    last_error: str | None = None
    attempts_used = 0

    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        try:
            result = solver.solve(blind)
        except Exception as exc:  # noqa: BLE001 — 배치는 개별 실패를 레코드로 남기고 계속
            last_error = str(exc)
            continue
        chosen = result.chosen_index
        walkthrough = result.rationale
        model = result.model
        if chosen == correct:
            status = STATUS_VERIFIED
            break
        status = STATUS_PARSE_FAILED if chosen == -1 else STATUS_MISMATCH

    record: dict[str, Any] = {
        "schema": EXPLANATION_SCHEMA,
        "question_id": question["question_id"],
        "exam": question.get("exam"),
        "subject": question["subject"],
        "unit": question.get("unit"),
        "applicable_year": question.get("applicable_year"),
        "model": model,
        "chosen_index": chosen,
        "correct_choice": correct,
        "answer_match": chosen == correct,
        "status": status,
        # 검수 관점 상태: 정답 일치라도 풀이 과정 채점(judge)은 별도 축이다.
        "review_status": "ai_generated_answer_verified"
        if status == STATUS_VERIFIED
        else "needs_review",
        "walkthrough": walkthrough,
        "quality_flags": {
            "table_lossy": bool(question.get("table_lossy")),
            "math_lossy": bool(question.get("math_lossy")),
        },
        "attempts": attempts_used,
        "duration_seconds": round(time.perf_counter() - started, 2),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if last_error is not None and status == STATUS_BACKEND_ERROR:
        record["error"] = last_error[-500:]
    return record


def explanation_path(out_dir: Path, question: dict[str, Any]) -> Path:
    year = question.get("applicable_year") or 0
    return Path(out_dir) / str(year) / f"{question['question_id']}.explanation.json"


def run_batch(
    questions: list[dict[str, Any]],
    solver: Any,
    out_dir: Path | str,
    *,
    skip_existing: bool = True,
    max_attempts: int = 2,
    progress: Any = None,
) -> dict[str, Any]:
    """배치 실행. 문항당 1파일 저장 — 파일 존재 = 완료 = 재실행 시 스킵.

    mismatch/parse_failed도 저장한다(재시도로 덮으려면 파일 삭제 후 재실행).
    backend_error는 저장하지 않는다 — 일시적 서버 다운이 체크포인트를 오염시키면
    (파일 존재=완료=스킵) 재실행이 그 문항들을 영원히 건너뛴다(실사고: ollama
    다운으로 backend_error 500건이 파일로 저장돼 배치가 무의미하게 완주됨).
    연속 5회 backend_error면 서버 다운으로 판단하고 배치를 중단한다.
    반환: 상태별 카운트 요약.
    """
    out = Path(out_dir)
    counts: dict[str, int] = {"skipped_existing": 0}
    consecutive_backend_errors = 0
    for i, question in enumerate(questions, start=1):
        path = explanation_path(out, question)
        if skip_existing and path.exists():
            counts["skipped_existing"] += 1
            continue
        record = generate_explanation(question, solver, max_attempts=max_attempts)
        counts[record["status"]] = counts.get(record["status"], 0) + 1
        if record["status"] == STATUS_BACKEND_ERROR:
            consecutive_backend_errors += 1
            if progress is not None:
                progress(
                    f"[{i}/{len(questions)}] {question['question_id']} "
                    f"→ backend_error (미저장: {record.get('error', '')[:120]})"
                )
            if consecutive_backend_errors >= 5:
                if progress is not None:
                    progress("backend_error 연속 5회 — 서버 다운으로 판단, 배치 중단")
                break
            continue
        consecutive_backend_errors = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if progress is not None:
            progress(
                f"[{i}/{len(questions)}] {question['question_id']} "
                f"→ {record['status']} ({record['duration_seconds']}s)"
            )
    return counts
