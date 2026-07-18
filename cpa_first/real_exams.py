"""실기출 로더 — parsed 문항 + 비전 복원 병합 + AI 해설 스토어.

data/real_exams/cpa1/
  parsed/<year>/<subject>.questions.json   파싱된 기출 (정답키 포함, 해설 없음)
  parsed/<year>/<subject>.recovered.json   비전 복원분 (math_lossy stem/choices 교체)
  explanations/<year>/<qid>.explanation.json  AI 생성·정답검증 해설 (explain_gen 산출)

API(main.py)와 배치 스크립트가 같은 로더를 쓴다 — 병합 규칙이 한 곳에만 존재하도록.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 학습 루프에 서빙할 때 문항에 붙는 출처 태그.
SOURCE_REAL_EXAM = "real_exam"
SOURCE_SYNTHETIC = "synthetic"

EXPLANATION_SCHEMA = "real_exam_explanation.v1"

# 해설 status 값. verified만 학습자에게 해설 본문을 보여준다.
STATUS_VERIFIED = "verified_answer_match"
STATUS_MISMATCH = "answer_mismatch"
STATUS_PARSE_FAILED = "answer_parse_failed"
STATUS_BACKEND_ERROR = "backend_error"


def load_real_exam_questions(
    base_dir: Path | str,
    *,
    years: list[int] | None = None,
    subjects: list[str] | None = None,
    apply_recovered: bool = True,
) -> list[dict[str, Any]]:
    """parsed/ 아래 전 연도·과목 문항 로드. recovered 파일이 있으면 원본에 덮어 병합.

    반환 순서는 (year, subject, question_id)로 결정론적.
    """
    parsed_dir = Path(base_dir) / "parsed"
    if not parsed_dir.exists():
        return []

    questions: list[dict[str, Any]] = []
    for year_dir in sorted(p for p in parsed_dir.iterdir() if p.is_dir()):
        if years and int(year_dir.name) not in years:
            continue
        # 복원분을 먼저 인덱싱 — 같은 연도 원본 위에 덮는다.
        recovered_by_id: dict[str, dict[str, Any]] = {}
        if apply_recovered:
            for rec_path in sorted(year_dir.glob("*.recovered.json")):
                for item in json.loads(rec_path.read_text(encoding="utf-8")):
                    recovered_by_id[item["question_id"]] = item

        for q_path in sorted(year_dir.glob("*.questions.json")):
            for item in json.loads(q_path.read_text(encoding="utf-8")):
                if subjects and item.get("subject") not in subjects:
                    continue
                rec = recovered_by_id.get(item["question_id"])
                if rec is not None:
                    # 원본 필드 위에 복원 필드를 덮는다(stem/choices/review_status 교체,
                    # correct_choice는 복원본에도 있지만 없어도 원본이 남는다).
                    item = {**item, **rec}
                questions.append(item)
    questions.sort(key=lambda q: (q.get("applicable_year") or 0, q["subject"], q["question_id"]))
    return questions


# 2차(주관식) 과목 한국어명. 1차 SUBJECTS 레지스트리와 분리 — 2차 트랙은
# 진단/처방 엔진에 연결되지 않는 읽기 전용 참고 자산이다(PRD가 2차를 명시 제외).
CPA2_SUBJECT_NAMES = {
    "tax": "세법",
    "financial_management": "재무관리",
    "audit": "회계감사",
    "cost_accounting": "원가관리회계",
    "financial_accounting": "재무회계",
}


def load_cpa2_subjective(base_dir: Path | str) -> list[dict[str, Any]]:
    """2차 주관식 파싱 문항 로드. 모범답안·채점기준은 비공개(null)로 정직 태깅.

    반환 순서는 (year, subject, question_id)로 결정론적. 없으면 빈 리스트.
    """
    parsed_dir = Path(base_dir) / "parsed"
    if not parsed_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for year_dir in sorted(p for p in parsed_dir.iterdir() if p.is_dir()):
        for path in sorted(year_dir.glob("*.subjective.json")):
            items.extend(json.loads(path.read_text(encoding="utf-8")))
    items.sort(key=lambda q: (q.get("applicable_year") or 0, q["subject"], q["question_id"]))
    return items


def load_explanations(explanations_dir: Path | str) -> dict[str, dict[str, Any]]:
    """explanations/ 아래 전 해설 레코드를 question_id로 인덱싱해 반환."""
    base = Path(explanations_dir)
    if not base.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(base.rglob("*.explanation.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        records[record["question_id"]] = record
    return records


def build_practice_entry(
    question: dict[str, Any], explanation: dict[str, Any] | None
) -> dict[str, Any]:
    """실기출 문항을 /practice 학습 루프 항목으로 변환.

    해설은 정답키 일치 검증(STATUS_VERIFIED)을 통과한 것만 본문을 싣는다.
    나머지는 explanation_kind='none'으로 정직하게 비워둔다 — 오답일 수 있는
    AI 해설을 학습자에게 공식 해설처럼 보여주지 않는다.
    """
    verified = explanation is not None and explanation.get("status") == STATUS_VERIFIED
    entry = {
        "question_id": question["question_id"],
        "exam": question.get("exam"),
        "subject": question["subject"],
        "unit": question.get("unit"),
        "applicable_year": question.get("applicable_year"),
        "stem": question["stem"],
        "choices": question["choices"],
        "correct_choice": question["correct_choice"],
        "concept_tags": [],
        "tutorial_id": None,
        "source": SOURCE_REAL_EXAM,
        "review_status": question.get("review_status"),
        "quality_flags": {
            "table_lossy": bool(question.get("table_lossy")),
            "math_lossy": bool(question.get("math_lossy")),
        },
        "explanation": explanation["walkthrough"] if verified else "",
        "explanation_kind": "ai_verified_answer_match" if verified else "none",
    }
    if explanation is not None:
        entry["explanation_status"] = explanation.get("status")
        entry["explanation_model"] = explanation.get("model")
    return entry
