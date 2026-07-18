"""학습 루프 API 통합 테스트 — 추천/로드맵/튜토리얼/연습/AI해설/학습경로.

"따라가기만 하면 되는" 루프 검증:
진단 → 처방(풀 문항+로드맵) → 연습(정답 비노출) → 시도 진단(해설) → 학습경로.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

DIAGNOSE_PAYLOAD: dict = {
    "target_exam": "CPA_1",
    "days_until_exam": 90,
    "available_hours_per_day": 6,
    "current_stage": "past_exam_rotation",
    "subject_states": [
        {
            "subject": "accounting",
            "accuracy": 0.55,
            "time_overrun_rate": 0.35,
            "risk_tags": ["time_pressure"],
            "concept_mastery": [{"concept": "재무회계: 금융자산", "mastery": 0.4}],
        },
        {
            "subject": "tax",
            "accuracy": 0.35,  # 과락 위험 — 최우선 추천 대상
            "time_overrun_rate": 0.2,
            "risk_tags": [],
        },
        {
            "subject": "business",
            "accuracy": 0.85,  # 안정권 — skip 후보
            "time_overrun_rate": 0.1,
            "risk_tags": [],
        },
    ],
}


# ── 처방: 풀 문항 추천 + 다주차 로드맵 ─────────────────────────────


def test_prescription_fills_problems_to_solve(client: TestClient):
    r = client.post("/diagnose", json=DIAGNOSE_PAYLOAD)
    assert r.status_code == 200, r.text
    rx = r.json()["prescription"]

    solve = rx["problems_to_solve"]
    assert len(solve) >= 1, "처방이 풀 문항을 추천하지 않음 — 따라갈 수 없는 처방"
    top = solve[0]
    assert top["subject"] == "tax", "과락 위험(35%) 과목이 최우선이어야 함"
    assert top["reason"]
    assert top["evidence_refs"][0]["ref_type"] == "problem_solution_map"

    skip = rx["problems_to_skip"]
    assert len(skip) >= 1
    assert skip[0]["subject"] == "business", "안정권(85%) 과목이 skip 대상"
    assert "안정권" in skip[0]["reason"]


def test_prescription_includes_study_plan(client: TestClient):
    r = client.post("/diagnose", json=DIAGNOSE_PAYLOAD)
    plan = r.json()["prescription"]["study_plan"]
    assert plan["total_weeks"] >= 1
    assert plan["pass_bar"] == {"average": 0.60, "per_subject_floor": 0.40}
    assert len(plan["weeks"]) == plan["total_weeks"]
    week1 = plan["weeks"][0]
    assert week1["subject_allocation"], "주차별 과목 배분이 비어 있음"
    assert week1["verification_metric"]


def test_recommendation_deprioritizes_attempted(client: TestClient):
    """시도한 문항은 추천 우선순위가 내려간다."""
    first = client.post("/diagnose", json=DIAGNOSE_PAYLOAD).json()["prescription"]
    top_qid = first["problems_to_solve"][0]["question_id"]

    r = client.post("/attempts/diagnose", json={"question_id": top_qid, "selected_choice": 0})
    assert r.status_code == 200, r.text

    second = client.post("/diagnose", json=DIAGNOSE_PAYLOAD).json()["prescription"]
    second_ids = [p["question_id"] for p in second["problems_to_solve"]]
    assert second_ids[0] != top_qid, "시도한 문항이 여전히 1순위 — 감점 미적용"


# ── 튜토리얼 ─────────────────────────────────────────────────────


def test_tutorials_list_and_detail(anon_client: TestClient):
    r = anon_client.get("/tutorials")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 4
    first = body["tutorials"][0]
    assert {"tutorial_id", "title", "subject_id", "n_steps"} <= set(first)

    detail = anon_client.get(f"/tutorials/{first['tutorial_id']}")
    assert detail.status_code == 200
    assert len(detail.json()["steps"]) == first["n_steps"]


def test_tutorials_subject_filter_and_404(anon_client: TestClient):
    # API 표준 과목 ID(tax)로 필터 — 시드 내부 ID(cpa1_tax 등)도 매칭되어야 한다
    r = anon_client.get("/tutorials", params={"subject": "tax"})
    tutorials = r.json()["tutorials"]
    assert tutorials, "표준 과목 ID 필터가 빈 결과 — 시드 내부 ID와 정규화 매칭 실패"
    assert all(t["subject_id"] == "tax" or t["subject_id"].endswith("_tax") for t in tutorials)
    assert anon_client.get("/tutorials/no-such-tutorial").status_code == 404


# ── 정답 포함 evidence 게이트 (공개 우회 차단) ─────────────────────


def test_solution_map_evidence_gated(app, client: TestClient, anon_client: TestClient):
    """공개 /practice의 question_id로 /evidence를 호출해 정답키를 얻는 우회 차단."""
    qid = client.get("/practice", params={"limit": 1}).json()["questions"][0]["question_id"]

    assert anon_client.get(f"/evidence/problem_solution_map/{qid}").status_code == 401
    assert client.get(f"/evidence/problem_solution_map/{qid}").status_code == 403

    client.post("/attempts/diagnose", json={"question_id": qid, "selected_choice": 0})
    r = client.get(f"/evidence/problem_solution_map/{qid}")
    assert r.status_code == 200
    assert "correct_choice" in r.json()["data"]


def test_solution_path_evidence_gated(client: TestClient):
    qid = client.get("/practice", params={"limit": 1}).json()["questions"][0]["question_id"]
    attempt = client.post(
        "/attempts/diagnose", json={"question_id": qid, "selected_choice": 0}
    ).json()
    path_ref = next(
        ref for ref in attempt["diagnosis"]["evidence_refs"] if ref["ref_type"] == "solution_path"
    )
    assert client.get(f"/evidence/solution_path/{path_ref['ref_id']}").status_code == 200


# ── 연습 문항 (정답 비노출) ───────────────────────────────────────


def test_practice_list_no_answer_leak(anon_client: TestClient):
    r = anon_client.get("/practice", params={"subject": "tax", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert 1 <= body["count"] <= 5
    for q in body["questions"]:
        assert q["subject"] == "tax"
        assert "correct_choice" not in q
        assert "explanation" not in q
        assert "solution_paths" not in q


def test_practice_cursor_pagination(anon_client: TestClient):
    page1 = anon_client.get("/practice", params={"limit": 3}).json()
    assert page1["next_cursor"] == page1["questions"][-1]["question_id"]
    page2 = anon_client.get("/practice", params={"limit": 3, "after": page1["next_cursor"]}).json()
    ids1 = {q["question_id"] for q in page1["questions"]}
    ids2 = {q["question_id"] for q in page2["questions"]}
    assert not ids1 & ids2, "커서 페이지가 겹침"


def test_practice_detail_has_stem_but_no_key(anon_client: TestClient):
    listed = anon_client.get("/practice", params={"limit": 1}).json()["questions"][0]
    r = anon_client.get(f"/practice/{listed['question_id']}")
    assert r.status_code == 200
    q = r.json()
    assert q["stem"] and len(q["choices"]) >= 4
    assert "correct_choice" not in q and "explanation" not in q
    assert anon_client.get("/practice/no-such-question").status_code == 404


def test_attempt_diagnose_returns_explanation(client: TestClient):
    qid = client.get("/practice", params={"limit": 1}).json()["questions"][0]["question_id"]
    r = client.post("/attempts/diagnose", json={"question_id": qid, "selected_choice": 0})
    assert r.status_code == 200
    assert r.json()["explanation"], "시도 후 공식 해설이 제공되어야 한다"


# ── AI 풀이 해설 ─────────────────────────────────────────────────


@dataclass
class _FakeResult:
    question_id: str
    chosen_index: int
    rationale: str
    mode: str = "live"
    model: str = "fake:test"


class _FakeSolver:
    def __init__(self, chosen_index: int):
        self.chosen_index = chosen_index
        self.seen_questions: list[dict] = []

    def solve(self, question: dict) -> _FakeResult:
        self.seen_questions.append(question)
        return _FakeResult(
            question_id=question["question_id"],
            chosen_index=self.chosen_index,
            rationale="1회전: 조건 정리. 2회전: 검산 후 확정.",
        )


def _attempt_first(client: TestClient) -> str:
    """ai-explain은 시도한 문항에만 허용 — 시도 후 question_id 반환."""
    qid = client.get("/practice", params={"limit": 1}).json()["questions"][0]["question_id"]
    r = client.post("/attempts/diagnose", json={"question_id": qid, "selected_choice": 0})
    assert r.status_code == 200, r.text
    return qid


def test_ai_explain_503_when_unconfigured(client: TestClient):
    qid = _attempt_first(client)
    r = client.post(f"/practice/{qid}/ai-explain")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_ai_explain_requires_auth(anon_client: TestClient):
    assert anon_client.post("/practice/x/ai-explain").status_code == 401


def test_ai_explain_403_before_attempt(app, client: TestClient):
    """시도하지 않은 문항의 AI 해설 요청 차단 — /practice 정답 비노출 경계 우회 방지."""
    app.state.ai_solver = _FakeSolver(chosen_index=0)
    qid = client.get("/practice", params={"limit": 1}).json()["questions"][0]["question_id"]
    r = client.post(f"/practice/{qid}/ai-explain")
    assert r.status_code == 403


def test_ai_explain_with_injected_solver(app, client: TestClient):
    qid = _attempt_first(client)
    detail = client.get(f"/practice/{qid}").json()

    # 정답 인덱스를 알 수 없으므로(비노출 설계) 0번 선택 fake로 두 경로 모두 검증
    fake = _FakeSolver(chosen_index=0)
    app.state.ai_solver = fake
    r = client.post(f"/practice/{qid}/ai-explain")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["walkthrough"]
    assert body["official_explanation"]
    assert isinstance(body["ai_matches_key"], bool)
    if not body["ai_matches_key"]:
        assert "불일치" in body["note"], "AI-정답키 불일치는 정직하게 표기되어야 한다"
    assert body["ai_chosen_index"] < len(detail["choices"])

    # solver에 정답 필드가 새지 않아야 한다 (blind dict 불변량)
    seen = fake.seen_questions[0]
    for forbidden in ("correct_choice", "correct_answer", "explanation"):
        assert forbidden not in seen, f"solver 입력에 {forbidden} 누수"


# ── 학습 경로 ─────────────────────────────────────────────────────


def test_learning_path_with_explicit_concepts(client: TestClient):
    r = client.get("/learning-path", params={"concepts": "재무회계: 기대신용손실"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"], "실데이터 선수개념 사슬이 비어 있음"
    depths = [n["depth"] for n in body["path"]]
    assert depths == sorted(depths, reverse=True), "깊은 선수개념부터 학습 순서여야 함"


def test_learning_path_404_without_prescription(client: TestClient):
    r = client.get("/learning-path")
    assert r.status_code == 404


def test_learning_path_from_active_prescription(client: TestClient):
    client.post("/diagnose", json=DIAGNOSE_PAYLOAD)
    r = client.get("/learning-path")
    assert r.status_code == 200, r.text
    assert "path" in r.json()


def test_learning_path_requires_auth(anon_client: TestClient):
    assert anon_client.get("/learning-path").status_code == 401


# ── 적대적 리뷰 적발 회귀 (정적 우회·blind 중첩 누수·중복 과목) ────


def test_static_answer_bank_blocked(anon_client: TestClient):
    """정적 마운트로 정답 은행 파일을 직접 받는 우회 차단."""
    r = anon_client.get("/problem_solution_maps.json")
    assert r.status_code == 404
    # 다른 정적 자원은 정상 서빙
    assert anon_client.get("/index.html").status_code == 200


def test_ai_explain_blind_excludes_nested_answers(app, client: TestClient):
    """blind 입력은 화이트리스트만 — solution_paths(answer_index 포함) 누수 차단."""
    qid = _attempt_first(client)
    fake = _FakeSolver(chosen_index=0)
    app.state.ai_solver = fake
    assert client.post(f"/practice/{qid}/ai-explain").status_code == 200
    seen = fake.seen_questions[0]
    assert "solution_paths" not in seen, "중첩 정답(solution_paths.answer_index) 누수"
    assert set(seen) <= {
        "question_id",
        "subject",
        "unit",
        "exam",
        "applicable_year",
        "stem",
        "choices",
        "concept_tags",
    }


def test_diagnose_rejects_duplicate_subjects(client: TestClient):
    """과목 중복 입력은 과락 floor 중복 적용으로 배분을 깨뜨림 — 422 거부."""
    payload = dict(DIAGNOSE_PAYLOAD)
    payload["subject_states"] = [
        {"subject": "tax", "accuracy": 0.3, "time_overrun_rate": 0.1, "risk_tags": []}
    ] * 3
    r = client.post("/diagnose", json=payload)
    assert r.status_code == 422


def test_study_plan_no_negative_hours_on_duplicates():
    """엔진 자체 방어 — 중복 과목 입력에도 음수 시간 불가(dedupe+클램프)."""
    from cpa_first.engine import build_study_plan

    state = {
        "user_id": "u1",
        "target_exam": "CPA_1",
        "days_until_exam": 30,
        "available_hours_per_day": 4,
        "current_stage": "objective_entry",
        "subject_states": [
            {"subject": "tax", "accuracy": 0.2, "time_overrun_rate": 0.1, "risk_tags": []}
        ]
        * 10,
    }
    plan = build_study_plan(state)
    for week in plan["weeks"]:
        for alloc in week["subject_allocation"]:
            assert alloc["hours"] >= 0, f"음수 배분: {alloc}"


def test_exam_core_tutorials_served_with_level_filter(anon_client):
    """exam_core 튜토리얼이 intro_low와 함께 서빙되고 level/ontology_node 필터가 동작한다."""
    all_t = anon_client.get("/tutorials").json()
    exam_core = anon_client.get("/tutorials", params={"level": "exam_core"}).json()
    intro = anon_client.get("/tutorials", params={"level": "intro_low"}).json()

    # 난이도 축이 실제로 존재 — exam_core가 다수 (감사 지적: 이전엔 intro_low 단일값)
    assert exam_core["count"] >= 40
    assert intro["count"] >= 20
    assert all_t["count"] == exam_core["count"] + intro["count"]
    assert all(t["level"] == "exam_core" for t in exam_core["tutorials"])

    # 재무회계 중급 핵심 단원이 실제로 커버됨 (감사: 유효이자율·수익인식 등 0개였음)
    nodes = {t["ontology_node"] for t in exam_core["tutorials"]}
    assert {"acct_revenue", "acct_financial_assets", "acct_income_tax"} <= nodes


def test_exam_core_tutorial_has_journal_entries(anon_client):
    """재무회계 exam_core 튜토리얼은 차변/대변 분개 표기를 포함한다 (감사: 0개였음)."""
    import json as _json

    detail = anon_client.get("/tutorials/tutorial_acct_revenue_exam_core")
    assert detail.status_code == 200
    body = _json.dumps(detail.json(), ensure_ascii=False)
    assert "차변" in body and "대변" in body
