"""FastAPI 통합 테스트 (다중 사용자 · DB · 인증).

진단→처방→근거 추적 End-to-end + 인증/인가/격리.
user_id는 토큰에서 주입되므로 요청 바디에 없다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

VALID_DIAGNOSE_PAYLOAD: dict = {
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


# ── Health (public) ────────────────────────────────────────────────


def test_health(anon_client: TestClient):
    response = anon_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["decision_rules"] >= 5
    assert data["problems"] >= 1
    assert data["db"] is True


def test_livez_readyz(anon_client: TestClient):
    assert anon_client.get("/livez").json()["status"] == "alive"
    rz = anon_client.get("/readyz")
    assert rz.status_code == 200
    assert rz.json()["db"] is True


# ── Auth gating ────────────────────────────────────────────────────


def test_diagnose_requires_auth(anon_client: TestClient):
    response = anon_client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_logs_require_auth(anon_client: TestClient):
    assert anon_client.get("/logs").status_code == 401
    assert anon_client.post("/logs", json={}).status_code == 401


# ── Diagnose / prescription (auth + per-user) ──────────────────────


def test_diagnose_returns_prescription(client: TestClient):
    response = client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "prescription" in body
    assert "user_state" in body
    rx = body["prescription"]
    assert rx["user_id"] == client.user_id
    assert rx["triggered_rule_keys"], "rules should match for this user"
    assert rx["evidence_refs"], "evidence_refs required"


def test_diagnose_persists_active_prescription(client: TestClient):
    diag = client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD).json()
    response = client.get("/prescription")
    assert response.status_code == 200
    assert response.json() == diag


def test_prescription_404_without_diagnose(client: TestClient):
    assert client.get("/prescription").status_code == 404


def test_diagnose_idempotent_same_inputs(client: TestClient):
    """동일 입력 재진단은 결정적 prescription_id를 갱신(upsert) — 500 PK 충돌 없음."""
    r1 = client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD)
    assert r1.status_code == 200, r1.text
    r2 = client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD)
    assert r2.status_code == 200, r2.text
    assert (
        r2.json()["prescription"]["prescription_id"] == r1.json()["prescription"]["prescription_id"]
    )
    assert client.get("/prescription").status_code == 200


def test_get_problem(anon_client: TestClient):
    response = anon_client.get("/problems/cpa1-accounting-002")
    assert response.status_code == 200
    body = response.json()
    assert body["problem_id"] == "cpa1-accounting-002"
    assert body["subject"] == "accounting"


def test_get_problem_404(anon_client: TestClient):
    assert anon_client.get("/problems/does-not-exist").status_code == 404


def test_evidence_resolves_decision_rule(client: TestClient):
    rx = client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD).json()["prescription"]
    rule_refs = [r for r in rx["evidence_refs"] if r["ref_type"] == "decision_rule"]
    assert rule_refs, "decision_rule evidence_refs 있어야 함"
    for ref in rule_refs:
        response = client.get(f"/evidence/decision_rule/{ref['ref_id']}")
        assert response.status_code == 200, response.text
        assert response.json()["data"]["rule_key"] == ref["ref_id"]


def test_evidence_resolves_user_state(client: TestClient):
    client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD)
    response = client.get(f"/evidence/user_state/{client.user_id}")
    assert response.status_code == 200
    assert response.json()["data"]["user_id"] == client.user_id


def test_evidence_user_state_forbidden_for_other(client: TestClient):
    client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD)
    response = client.get("/evidence/user_state/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 403


def test_evidence_resolves_problem_intelligence(anon_client: TestClient):
    response = anon_client.get("/evidence/problem_intelligence/cpa1-accounting-002")
    assert response.status_code == 200
    assert response.json()["data"]["problem_id"] == "cpa1-accounting-002"


def test_evidence_unknown_ref_type(anon_client: TestClient):
    assert anon_client.get("/evidence/success_case/some-case-id").status_code == 501


def test_evidence_unknown_rule_id(anon_client: TestClient):
    assert anon_client.get("/evidence/decision_rule/does_not_exist").status_code == 404


def test_diagnose_validates_input(client: TestClient):
    bad = {
        "days_until_exam": -1,
        "available_hours_per_day": 8,
        "current_stage": "post_lecture",
        "subject_states": [],
    }
    assert client.post("/diagnose", json=bad).status_code == 422


def test_diagnose_invalid_stage(client: TestClient):
    bad = dict(VALID_DIAGNOSE_PAYLOAD, current_stage="banana")
    assert client.post("/diagnose", json=bad).status_code == 422


def test_diagnose_changes_prescription_on_state_change(client: TestClient):
    payload_a = dict(VALID_DIAGNOSE_PAYLOAD, current_stage="past_exam_rotation")
    payload_b = dict(VALID_DIAGNOSE_PAYLOAD, current_stage="final", days_until_exam=20)
    rx_a = client.post("/diagnose", json=payload_a).json()["prescription"]
    rx_b = client.post("/diagnose", json=payload_b).json()["prescription"]
    assert rx_a["triggered_rule_keys"] != rx_b["triggered_rule_keys"]


def test_end_to_end_evidence_walk(client: TestClient):
    rx = client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD).json()["prescription"]
    visited = 0
    for ref in rx["evidence_refs"]:
        if ref["ref_type"] in {"decision_rule", "problem_intelligence", "user_state"}:
            r = client.get(f"/evidence/{ref['ref_type']}/{ref['ref_id']}")
            assert r.status_code == 200, f"evidence walk failed: {ref}"
            visited += 1
    assert visited == len(rx["evidence_refs"]), "지원 ref_type 외 evidence가 섞여 있음"


# ── 다중 사용자 격리 (IDOR) ─────────────────────────────────────────


def test_user_data_isolated_between_accounts(client: TestClient, app):
    """user A가 진단/로그를 남겨도 user B에게는 보이지 않는다."""
    client.post("/diagnose", json=VALID_DIAGNOSE_PAYLOAD)
    client.post("/logs", json=_log_payload(1, "cpa1-accounting-002", True, 80))

    # 두 번째 사용자
    other = TestClient(app)
    from tests.conftest import register

    tok = register(other, "other@test.com")["access_token"]
    other.headers.update({"Authorization": f"Bearer {tok}"})

    assert other.get("/prescription").status_code == 404
    assert other.get("/logs").json()["count"] == 0
    assert other.get("/attempts").json()["count"] == 0


# ── MistakeLog (auth + per-user) ───────────────────────────────────


def _log_payload(
    idx: int,
    problem_id: str,
    correct: bool,
    time_seconds: int,
    *,
    mistakes: list[str] | None = None,
) -> dict:
    return {
        "log_id": f"log-{idx}",
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
    r2 = client.post(
        "/logs", json=_log_payload(2, "cpa1-tax-001", False, 200, mistakes=["memory_decay"])
    )
    assert r2.json()["log_count"] == 2
    listing = client.get("/logs").json()
    assert listing["count"] == 2
    assert {entry["log_id"] for entry in listing["logs"]} == {"log-1", "log-2"}


def test_logs_idempotent(client: TestClient):
    client.post("/logs", json=_log_payload(1, "cpa1-accounting-002", True, 80))
    client.post("/logs", json=_log_payload(1, "cpa1-accounting-002", True, 80))
    assert client.get("/logs").json()["count"] == 1


def test_logs_rejects_unknown_problem(client: TestClient):
    bad = _log_payload(1, "no-such-problem", True, 80)
    assert client.post("/logs", json=bad).status_code == 400


def test_user_state_refresh_requires_logs(client: TestClient):
    response = client.post(
        "/user-state/refresh",
        json={
            "days_until_exam": 90,
            "available_hours_per_day": 8,
            "current_stage": "past_exam_rotation",
        },
    )
    assert response.status_code == 400


def test_user_state_refresh_aggregates_logs(client: TestClient):
    client.post("/logs", json=_log_payload(1, "cpa1-accounting-002", True, 80))
    client.post("/logs", json=_log_payload(2, "cpa1-accounting-003", True, 90))
    client.post(
        "/logs", json=_log_payload(3, "cpa1-accounting-004", False, 200, mistakes=["time_pressure"])
    )
    client.post(
        "/logs",
        json=_log_payload(4, "cpa1-tax-001", False, 150, mistakes=["memory_decay", "concept_gap"]),
    )
    client.post(
        "/logs", json=_log_payload(5, "cpa1-tax-002", False, 145, mistakes=["memory_decay"])
    )

    response = client.post(
        "/user-state/refresh",
        json={
            "days_until_exam": 90,
            "available_hours_per_day": 8,
            "current_stage": "past_exam_rotation",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    by_subject = {s["subject"]: s for s in body["user_state"]["subject_states"]}
    assert by_subject["accounting"]["accuracy"] == pytest.approx(2 / 3, abs=1e-3)
    assert by_subject["tax"]["accuracy"] == 0.0
    assert "memory_decay" in by_subject["tax"]["risk_tags"]
    assert body["prescription"]["triggered_rule_keys"]

    again = client.get("/prescription").json()
    assert again == body


def test_clear_logs(client: TestClient):
    client.post("/logs", json=_log_payload(1, "cpa1-accounting-002", True, 80))
    assert client.get("/logs").json()["count"] == 1
    assert client.delete("/logs").status_code == 200
    assert client.get("/logs").json()["count"] == 0


# ── 응시 진단 (auth + per-user) ────────────────────────────────────


def test_attempt_diagnose_returns_concept_gap_and_persists(client: TestClient):
    response = client.post(
        "/attempts/diagnose",
        json={
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
    # attempt_id는 서버 생성 (클라이언트 지정 불가)
    server_attempt_id = body["attempt"]["attempt_id"]
    assert server_attempt_id

    listing = client.get("/attempts").json()
    assert listing["count"] == 1
    assert listing["attempts"][0]["attempt_id"] == server_attempt_id


def test_attempt_diagnose_rejects_unknown_problem_map(client: TestClient):
    response = client.post(
        "/attempts/diagnose", json={"question_id": "not-a-map", "selected_choice": 0}
    )
    assert response.status_code == 404


# ── 검수 워크플로우 (ADMIN only, DB override) ───────────────────────


def test_review_requires_admin(client: TestClient):
    """일반 사용자는 검수 불가 (403)."""
    response = client.post(
        "/review/decision_rule/objective_entry_timing",
        json={"review_status": "human_reviewed"},
    )
    assert response.status_code == 403


def test_review_requires_auth(anon_client: TestClient):
    response = anon_client.post(
        "/review/decision_rule/objective_entry_timing",
        json={"review_status": "human_reviewed"},
    )
    assert response.status_code == 401


def test_review_decision_rule(admin_client: TestClient):
    response = admin_client.post(
        "/review/decision_rule/objective_entry_timing",
        json={"review_status": "human_reviewed", "reviewer": "tester"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["previous_status"] is None  # 첫 override
    assert body["review_status"] == "human_reviewed"
    # /evidence 오버레이로 effective status 반영 (시드 파일은 불변)
    ev = admin_client.get("/evidence/decision_rule/objective_entry_timing").json()
    assert ev["data"]["review_status"] == "human_reviewed"


def test_review_problem_intelligence(admin_client: TestClient):
    response = admin_client.post(
        "/review/problem_intelligence/cpa1-accounting-002",
        json={"review_status": "expert_reviewed", "reviewer": "tester"},
    )
    assert response.status_code == 200
    assert response.json()["review_status"] == "expert_reviewed"
    refreshed = admin_client.get("/problems/cpa1-accounting-002").json()
    assert refreshed["review_status"] == "expert_reviewed"


def test_review_rejects_invalid_status_for_ref_type(admin_client: TestClient):
    response = admin_client.post(
        "/review/decision_rule/objective_entry_timing", json={"review_status": "ai_draft"}
    )
    assert response.status_code == 422


def test_review_invalid_ref_id(admin_client: TestClient):
    response = admin_client.post("/review/decision_rule/bad@id", json={"review_status": "approved"})
    assert response.status_code == 422


def test_review_unknown_ref_type(admin_client: TestClient):
    response = admin_client.post("/review/user_state/foo", json={"review_status": "approved"})
    assert response.status_code == 400


def test_review_not_found(admin_client: TestClient):
    response = admin_client.post(
        "/review/decision_rule/does_not_exist", json={"review_status": "approved"}
    )
    assert response.status_code == 404
