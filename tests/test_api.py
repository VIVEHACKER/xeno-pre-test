"""FastAPI 통합 테스트.

07-implementation-plan.md M3 검증: 진단→처방→근거 추적 End-to-end 동작.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cpa_first.api import create_app
from cpa_first.api import main as api_main


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """active_user_state/prescription/logs 저장 경로를 임시 디렉터리로 분리."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(api_main, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(api_main, "ACTIVE_USER_STATE_PATH", runtime / "active_user_state.json")
    monkeypatch.setattr(api_main, "ACTIVE_PRESCRIPTION_PATH", runtime / "active_prescription.json")
    monkeypatch.setattr(api_main, "MISTAKE_LOGS_PATH", runtime / "mistake_logs.jsonl")
    monkeypatch.setattr(api_main, "ATTEMPT_DIAGNOSES_PATH", runtime / "attempt_diagnoses.jsonl")
    return runtime


@pytest.fixture
def isolated_seeds(tmp_path: Path) -> tuple[Path, Path]:
    """검수 테스트는 시드 파일을 직접 쓰므로 시드를 임시 디렉터리에 복사한다."""
    rules_src = ROOT / "data" / "seeds" / "decision_rules"
    problems_src = ROOT / "data" / "seeds" / "problems"
    rules_dst = tmp_path / "rules"
    problems_dst = tmp_path / "problems"
    rules_dst.mkdir()
    problems_dst.mkdir()
    for f in rules_src.glob("*.decision_rule.json"):
        (rules_dst / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    for f in problems_src.glob("*.problem_intelligence.json"):
        (problems_dst / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    return rules_dst, problems_dst


@pytest.fixture
def client(isolated_runtime) -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def review_client(isolated_runtime, isolated_seeds) -> TestClient:
    rules_dir, problems_dir = isolated_seeds
    return TestClient(create_app(rules_dir=rules_dir, problems_dir=problems_dir))


VALID_DIAGNOSE_PAYLOAD: dict = {
    "user_id": "test-user",
    "target_exam": "CPA_1",
    "days_until_exam": 90,
    "available_hours_per_day": 8,
    "current_stage": "past_exam_rotation",
    "subject_states": [
        {
            "subject": "accounting",
            "accuracy": 0.55,
            "time_overrun_rate": 0.35,
            "risk_tags": ["time_pressure", "rotation_confusion"],
            "concept_mastery": [
                {"concept": "재무회계: 금융자산", "mastery": 0.6},
                {"concept": "재무회계: 수익인식", "mastery": 0.48},
            ],
        },
        {
            "subject": "tax",
            "accuracy": 0.5,
            "time_overrun_rate": 0.2,
            "risk_tags": ["memory_decay"],
            "concept_mastery": [
                {"concept": "세법: 법인세 손금", "mastery": 0.55},
            ],
        },
    ],
}


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["decision_rules"] >= 5
    assert data["problems"] >= 1


def test_diagnose_returns_prescription(client: TestClient):
    response = client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "prescription" in body
    assert "user_state" in body
    rx = body["prescription"]
    assert rx["user_id"] == "test-user"
    assert rx["triggered_rule_keys"], "rules should match for this user"
    assert rx["evidence_refs"], "evidence_refs required"


def test_diagnose_persists_active_prescription(client: TestClient):
    """진단 후 GET /prescription이 같은 처방을 반환."""
    diag = client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD).json()
    response = client.get("/prescription")
    assert response.status_code == 200
    assert response.json() == diag


def test_prescription_404_without_diagnose(client: TestClient):
    response = client.get("/prescription")
    assert response.status_code == 404


def test_get_problem(client: TestClient):
    response = client.get("/problems/cpa1-accounting-002")
    assert response.status_code == 200
    body = response.json()
    assert body["problem_id"] == "cpa1-accounting-002"
    assert body["subject"] == "accounting"


def test_get_problem_404(client: TestClient):
    response = client.get("/problems/does-not-exist")
    assert response.status_code == 404


def test_evidence_resolves_decision_rule(client: TestClient):
    """처방의 evidence_refs를 따라가면 실제 데이터에 도달한다 (End-to-end)."""
    rx = client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD).json()["prescription"]
    rule_refs = [r for r in rx["evidence_refs"] if r["ref_type"] == "decision_rule"]
    assert rule_refs, "decision_rule evidence_refs 있어야 함"

    for ref in rule_refs:
        response = client.get(f"/evidence/decision_rule/{ref['ref_id']}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["data"]["rule_key"] == ref["ref_id"]


def test_evidence_resolves_user_state(client: TestClient):
    client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD)
    response = client.get(f"/evidence/user_state/{VALID_DIAGNOSE_PAYLOAD['user_id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["user_id"] == VALID_DIAGNOSE_PAYLOAD["user_id"]


def test_evidence_resolves_problem_intelligence(client: TestClient):
    response = client.get("/evidence/problem_intelligence/cpa1-accounting-002")
    assert response.status_code == 200
    assert response.json()["data"]["problem_id"] == "cpa1-accounting-002"


def test_evidence_unknown_ref_type(client: TestClient):
    response = client.get("/evidence/success_case/some-case-id")
    assert response.status_code == 501


def test_evidence_unknown_rule_id(client: TestClient):
    response = client.get("/evidence/decision_rule/does_not_exist")
    assert response.status_code == 404


def test_diagnose_validates_input(client: TestClient):
    bad = {
        "user_id": "x",
        "days_until_exam": -1,
        "available_hours_per_day": 8,
        "current_stage": "post_lecture",
        "subject_states": [],
    }
    response = client.post("/diagnose", json=bad)
    assert response.status_code == 422


def test_diagnose_invalid_stage(client: TestClient):
    bad = dict(VALID_DIAGNOSE_PAYLOAD, current_stage="banana")
    response = client.post("/diagnose", json=bad)
    assert response.status_code == 422


def test_diagnose_changes_prescription_on_state_change(client: TestClient):
    """End-to-end 민감도: 단계가 바뀌면 처방의 triggered_rule_keys가 달라진다."""
    payload_a = dict(VALID_DIAGNOSE_PAYLOAD, current_stage="past_exam_rotation")
    payload_b = dict(VALID_DIAGNOSE_PAYLOAD, current_stage="final", days_until_exam=20)

    rx_a = client.post("/diagnose", json=payload_a).json()["prescription"]
    rx_b = client.post("/diagnose", json=payload_b).json()["prescription"]

    assert rx_a["triggered_rule_keys"] != rx_b["triggered_rule_keys"]


def test_end_to_end_evidence_walk(client: TestClient):
    """진단 → 처방 → 모든 근거 → 200 응답까지의 전 구간."""
    rx = client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD).json()["prescription"]

    visited = 0
    for ref in rx["evidence_refs"]:
        if ref["ref_type"] in {"decision_rule", "problem_intelligence", "user_state"}:
            r = client.get(f"/evidence/{ref['ref_type']}/{ref['ref_id']}")
            assert r.status_code == 200, f"evidence walk failed: {ref}"
            visited += 1

    assert visited == len(rx["evidence_refs"]), "지원 ref_type 외 evidence가 섞여 있음"


# ----- M5: MistakeLog + user-state/refresh -----


def _log_payload(idx: int, problem_id: str, correct: bool, time_seconds: int, *, mistakes: list[str] | None = None) -> dict:
    return {
        "log_id": f"log-{idx}",
        "user_id": "active-user",
        "problem_id": problem_id,
        "attempt_at": f"2026-05-11T00:{idx:02d}:00+00:00",
        "correct": correct,
        "time_seconds": time_seconds,
        "mistake_categories": mistakes or [],
    }


def test_logs_post_and_get(client: TestClient):
    r1 = client.post("/logs", json=_log_payload(1, "cpa1-accounting-002", True, 80))
    assert r1.status_code == 200
    assert r1.json()["log_count"] == 1
    r2 = client.post("/logs", json=_log_payload(2, "cpa1-tax-001", False, 200, mistakes=["memory_decay"]))
    assert r2.json()["log_count"] == 2

    listing = client.get("/logs").json()
    assert listing["count"] == 2
    assert {l["log_id"] for l in listing["logs"]} == {"log-1", "log-2"}


def test_logs_rejects_unknown_problem(client: TestClient):
    bad = _log_payload(1, "no-such-problem", True, 80)
    response = client.post("/logs", json=bad)
    assert response.status_code == 400


def test_user_state_refresh_requires_logs(client: TestClient):
    response = client.post(
        "/user-state/refresh",
        json={
            "user_id": "active-user",
            "days_until_exam": 90,
            "available_hours_per_day": 8,
            "current_stage": "past_exam_rotation",
        },
    )
    assert response.status_code == 400


def test_user_state_refresh_aggregates_logs(client: TestClient):
    # 회계 정답 2/3 + 시간초과 1건
    client.post("/logs", json=_log_payload(1, "cpa1-accounting-002", True, 80))
    client.post("/logs", json=_log_payload(2, "cpa1-accounting-003", True, 90))
    client.post(
        "/logs",
        json=_log_payload(3, "cpa1-accounting-004", False, 200, mistakes=["time_pressure"]),
    )
    # 세법 정답 0/2 + 휘발
    client.post(
        "/logs",
        json=_log_payload(4, "cpa1-tax-001", False, 150, mistakes=["memory_decay", "concept_gap"]),
    )
    client.post(
        "/logs",
        json=_log_payload(5, "cpa1-tax-002", False, 145, mistakes=["memory_decay"]),
    )

    response = client.post(
        "/user-state/refresh",
        json={
            "user_id": "active-user",
            "days_until_exam": 90,
            "available_hours_per_day": 8,
            "current_stage": "past_exam_rotation",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    us = body["user_state"]
    by_subject = {s["subject"]: s for s in us["subject_states"]}

    assert by_subject["accounting"]["accuracy"] == pytest.approx(2 / 3, abs=1e-3)
    assert by_subject["tax"]["accuracy"] == 0.0
    assert "memory_decay" in by_subject["tax"]["risk_tags"]

    # 자동 처방까지 산출되었는지
    rx = body["prescription"]
    assert rx["triggered_rule_keys"], "자동 산출된 user_state에 대해 매칭 규칙 있어야 함"

    # GET /prescription 재조회로 동일 처방 회수
    again = client.get("/prescription").json()
    assert again == body


def test_clear_logs(client: TestClient):
    client.post("/logs", json=_log_payload(1, "cpa1-accounting-002", True, 80))
    assert client.get("/logs").json()["count"] == 1
    delete_response = client.delete("/logs")
    assert delete_response.status_code == 200
    assert client.get("/logs").json()["count"] == 0


# ----- M8: 풀이맵 기반 응시 진단 -----


def test_attempt_diagnose_returns_concept_gap_and_persists(client: TestClient):
    response = client.post(
        "/attempts/diagnose",
        json={
            "attempt_id": "attempt-1",
            "user_id": "active-user",
            "question_id": "cpa1-eval-accounting-002",
            "selected_choice": 1,
            "time_seconds": 95,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    diagnosis = body["diagnosis"]
    assert diagnosis["correct"] is False
    assert diagnosis["correct_choice"] == 2
    assert diagnosis["recommended_path"]["path_type"] == "choice_elimination"
    assert "concept_gap" in diagnosis["mistake_tags"]
    assert len(diagnosis["missing_concept_links"]) == 3

    listing = client.get("/attempts").json()
    assert listing["count"] == 1
    assert listing["attempts"][0]["attempt_id"] == "attempt-1"


def test_attempt_diagnose_rejects_unknown_problem_map(client: TestClient):
    response = client.post(
        "/attempts/diagnose",
        json={
            "question_id": "not-a-map",
            "selected_choice": 0,
        },
    )

    assert response.status_code == 404


# ----- M4: 검수 워크플로우 -----


def test_review_decision_rule(review_client: TestClient):
    response = review_client.post(
        "/review/decision_rule/objective_entry_timing",
        json={"review_status": "human_reviewed", "reviewer": "tester"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["previous_status"] == "machine_draft"
    assert body["review_status"] == "human_reviewed"

    # /evidence 로 조회 시 메모리 캐시 동기화 확인
    ev = review_client.get("/evidence/decision_rule/objective_entry_timing").json()
    assert ev["data"]["review_status"] == "human_reviewed"


def test_review_problem_intelligence(review_client: TestClient):
    response = review_client.post(
        "/review/problem_intelligence/cpa1-accounting-002",
        json={"review_status": "expert_reviewed", "reviewer": "tester"},
    )
    assert response.status_code == 200
    assert response.json()["review_status"] == "expert_reviewed"

    refreshed = review_client.get("/problems/cpa1-accounting-002").json()
    assert refreshed["review_status"] == "expert_reviewed"


def test_review_rejects_invalid_status_for_ref_type(review_client: TestClient):
    # decision_rule에 ai_draft는 없음 (problem_intelligence 전용)
    response = review_client.post(
        "/review/decision_rule/objective_entry_timing",
        json={"review_status": "ai_draft"},
    )
    assert response.status_code == 422


def test_review_unknown_ref_type(review_client: TestClient):
    response = review_client.post(
        "/review/user_state/foo",
        json={"review_status": "approved"},
    )
    assert response.status_code == 400


def test_review_not_found(review_client: TestClient):
    response = review_client.post(
        "/review/decision_rule/does_not_exist",
        json={"review_status": "approved"},
    )
    assert response.status_code == 404
