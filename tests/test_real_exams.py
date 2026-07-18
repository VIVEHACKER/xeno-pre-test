"""실기출 로더 + 해설 생성 파이프라인 + /practice 통합 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cpa_first.explain_gen import (
    SOLVER_INPUT_FIELDS,
    build_blind_question,
    generate_explanation,
    run_batch,
)
from cpa_first.real_exams import (
    STATUS_MISMATCH,
    STATUS_PARSE_FAILED,
    STATUS_VERIFIED,
    build_practice_entry,
    load_explanations,
    load_real_exam_questions,
)


def _question(qid: str = "cpa1-real-2026-tax-001", **overrides) -> dict:
    base = {
        "question_id": qid,
        "exam": "CPA_1",
        "subject": "tax",
        "unit": None,
        "applicable_year": 2026,
        "stem": "법인세법상 손금에 산입되는 것은?",
        "choices": [
            "벌금",
            "접대비 한도초과액",
            "감가상각비(한도 내)",
            "임원 상여 한도초과",
            "폐수배출부담금",
        ],
        "correct_choice": 2,
        "table_lossy": False,
        "math_lossy": False,
        "split_overflow": False,
        "rights_status": "official_public",
        "review_status": "parsed",
        "source": "real_exam_pdf",
    }
    base.update(overrides)
    return base


class FakeSolver:
    """정답/오답/파싱실패를 시나리오대로 반환하는 주입용 solver."""

    def __init__(self, answers: list[int]):
        self.answers = list(answers)
        self.seen_questions: list[dict] = []

    def solve(self, question: dict):
        from cpa_first.solver import SolveResult

        self.seen_questions.append(question)
        chosen = self.answers.pop(0)
        return SolveResult(
            question_id=question["question_id"],
            chosen_index=chosen,
            rationale=f"풀이 근거 (chosen={chosen})",
            mode="live",
            model="fake:test",
        )


# ───────────────────────── 로더 ─────────────────────────


def _write_year(tmp_path: Path, year: int, items: list[dict], recovered: list[dict] | None = None):
    year_dir = tmp_path / "parsed" / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)
    (year_dir / "tax.questions.json").write_text(
        json.dumps(items, ensure_ascii=False), encoding="utf-8"
    )
    if recovered:
        (year_dir / "tax.recovered.json").write_text(
            json.dumps(recovered, ensure_ascii=False), encoding="utf-8"
        )


def test_loader_merges_recovered(tmp_path):
    lossy = _question(math_lossy=True, stem="[수식 손실]")
    recovered = _question(
        math_lossy=False, stem="복원된 수식 문제", review_status="vision_recovered"
    )
    _write_year(tmp_path, 2026, [lossy], [recovered])

    questions = load_real_exam_questions(tmp_path)
    assert len(questions) == 1
    assert questions[0]["stem"] == "복원된 수식 문제"
    assert questions[0]["review_status"] == "vision_recovered"
    assert questions[0]["math_lossy"] is False


def test_loader_filters_years_and_subjects(tmp_path):
    _write_year(tmp_path, 2025, [_question("cpa1-real-2025-tax-001", applicable_year=2025)])
    _write_year(tmp_path, 2026, [_question()])

    assert len(load_real_exam_questions(tmp_path)) == 2
    assert len(load_real_exam_questions(tmp_path, years=[2026])) == 1
    assert load_real_exam_questions(tmp_path, subjects=["accounting"]) == []


def test_loader_missing_dir_returns_empty(tmp_path):
    assert load_real_exam_questions(tmp_path / "nope") == []


# ───────────────────────── 해설 생성기 ─────────────────────────


def test_blind_question_excludes_answer_key():
    blind = build_blind_question(_question())
    assert "correct_choice" not in blind
    assert "correct_answer" not in blind
    assert set(blind) <= set(SOLVER_INPUT_FIELDS)
    assert blind["stem"]


def test_generate_verified_on_match():
    solver = FakeSolver([2])
    record = generate_explanation(_question(), solver)
    assert record["status"] == STATUS_VERIFIED
    assert record["answer_match"] is True
    assert record["review_status"] == "ai_generated_answer_verified"
    assert record["walkthrough"]
    # solver가 받은 입력에 정답키가 없어야 한다 (누수 가드)
    assert all("correct_choice" not in q for q in solver.seen_questions)


def test_generate_retries_then_mismatch():
    solver = FakeSolver([0, 1])  # 두 번 다 오답
    record = generate_explanation(_question(), solver, max_attempts=2)
    assert record["status"] == STATUS_MISMATCH
    assert record["attempts"] == 2
    assert record["review_status"] == "needs_review"


def test_generate_retry_recovers():
    solver = FakeSolver([-1, 2])  # 파싱 실패 → 재시도 정답
    record = generate_explanation(_question(), solver, max_attempts=2)
    assert record["status"] == STATUS_VERIFIED
    assert record["attempts"] == 2


def test_generate_parse_failed():
    solver = FakeSolver([-1])
    record = generate_explanation(_question(), solver, max_attempts=1)
    assert record["status"] == STATUS_PARSE_FAILED


def test_run_batch_checkpoint_resume(tmp_path):
    questions = [_question(), _question("cpa1-real-2026-tax-002")]
    out = tmp_path / "explanations"

    counts1 = run_batch(questions, FakeSolver([2, 0]), out)
    assert counts1 == {"skipped_existing": 0, STATUS_VERIFIED: 1, STATUS_MISMATCH: 1}

    # 재실행: 기존 파일 전부 스킵 — solver가 호출되지 않아야 한다
    solver2 = FakeSolver([])
    counts2 = run_batch(questions, solver2, out)
    assert counts2 == {"skipped_existing": 2}
    assert solver2.seen_questions == []

    records = load_explanations(out)
    assert len(records) == 2
    assert records["cpa1-real-2026-tax-001"]["status"] == STATUS_VERIFIED


# ───────────────────────── practice 항목 변환 ─────────────────────────


def test_practice_entry_gates_unverified_explanation():
    q = _question()
    verified = {"status": STATUS_VERIFIED, "walkthrough": "단계별 풀이", "model": "m"}
    mismatch = {"status": STATUS_MISMATCH, "walkthrough": "오답 풀이", "model": "m"}

    e1 = build_practice_entry(q, verified)
    assert e1["explanation"] == "단계별 풀이"
    assert e1["explanation_kind"] == "ai_verified_answer_match"

    e2 = build_practice_entry(q, mismatch)
    assert e2["explanation"] == ""  # 오답 해설은 학습자 비노출
    assert e2["explanation_kind"] == "none"

    e3 = build_practice_entry(q, None)
    assert e3["explanation"] == ""
    assert e3["source"] == "real_exam"


# ───────────────────────── API 통합 ─────────────────────────


@pytest.fixture
def real_exam_app(tmp_path):
    """실기출 2문항 + 검증 해설 1건을 가진 앱."""
    from cpa_first.api.main import create_app
    from cpa_first.config import get_settings

    q1 = _question()
    q2 = _question("cpa1-real-2026-tax-002", correct_choice=0)
    _write_year(tmp_path, 2026, [q1, q2])
    exp_dir = tmp_path / "explanations" / "2026"
    exp_dir.mkdir(parents=True)
    record = generate_explanation(q1, FakeSolver([2]))
    (exp_dir / f"{q1['question_id']}.explanation.json").write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )
    return create_app(settings=get_settings(), real_exams_dir=tmp_path)


@pytest.fixture
def real_client(real_exam_app) -> TestClient:
    from tests.conftest import register

    c = TestClient(real_exam_app)
    body = register(c, "real@test.com")
    c.headers.update({"Authorization": f"Bearer {body['access_token']}"})
    return c


def test_practice_lists_real_exam_with_filter(real_client):
    r = real_client.get("/practice", params={"source": "real_exam", "limit": 50})
    assert r.status_code == 200
    body = r.json()
    ids = [q["question_id"] for q in body["questions"]]
    assert "cpa1-real-2026-tax-001" in ids
    assert all(q["source"] == "real_exam" for q in body["questions"])
    # 목록에 정답·해설 본문 비노출
    assert all("correct_choice" not in q and "explanation" not in q for q in body["questions"])
    # 해설 보유 플래그만 노출
    by_id = {q["question_id"]: q for q in body["questions"]}
    assert by_id["cpa1-real-2026-tax-001"]["has_explanation"] is True
    assert by_id["cpa1-real-2026-tax-002"]["has_explanation"] is False


def test_practice_detail_serves_real_stem_without_key(real_client):
    r = real_client.get("/practice/cpa1-real-2026-tax-001")
    assert r.status_code == 200
    body = r.json()
    assert body["stem"]
    assert len(body["choices"]) == 5
    assert "correct_choice" not in body
    assert "explanation" not in body


def test_diagnose_real_exam_returns_verified_explanation(real_client):
    r = real_client.post(
        "/attempts/diagnose",
        json={"question_id": "cpa1-real-2026-tax-001", "selected_choice": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["diagnosis"]["correct"] is False
    assert body["diagnosis"]["correct_choice"] == 2
    assert body["diagnosis"]["recommended_path"] is None  # 실기출은 풀이경로 없음
    assert body["explanation"] == "풀이 근거 (chosen=2)"
    assert body["explanation_kind"] == "ai_verified_answer_match"


def test_diagnose_real_exam_without_explanation_says_none(real_client):
    r = real_client.post(
        "/attempts/diagnose",
        json={"question_id": "cpa1-real-2026-tax-002", "selected_choice": 0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["diagnosis"]["correct"] is True
    assert body["explanation"] == ""
    assert body["explanation_kind"] == "none"


def test_health_counts_real_exams(real_client):
    body = real_client.get("/health").json()
    assert body["real_exam_questions"] == 2
