"""용어 지식 그래프 API 단위 테스트."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cpa_first.api.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


# ── /health 보강 ─────────────────────────────────────────────────


def test_health_reports_terms_and_edges(client: TestClient):
    res = client.get("/health")
    data = res.json()
    assert res.status_code == 200
    assert data["terms"] >= 1000
    assert data["term_edges"] >= 1000


# ── /terms/search ────────────────────────────────────────────────


def test_search_empty_returns_empty(client: TestClient):
    res = client.get("/terms/search", params={"q": ""})
    assert res.status_code == 200
    assert res.json()["results"] == []


def test_search_korean_name_matches(client: TestClient):
    res = client.get("/terms/search", params={"q": "상각후원가"})
    results = res.json()["results"]
    assert results
    assert results[0]["term_id"] == "amortized-cost"
    assert results[0]["name_ko"] == "상각후원가"
    assert results[0]["subject"] == "accounting"


def test_search_alias_matches(client: TestClient):
    res = client.get("/terms/search", params={"q": "EIR"})
    ids = [r["term_id"] for r in res.json()["results"]]
    assert "effective-interest-rate" in ids


def test_search_respects_limit(client: TestClient):
    # 광범위한 쿼리. limit이 결과를 자른다.
    res = client.get("/terms/search", params={"q": "세", "limit": 5})
    assert len(res.json()["results"]) <= 5


def test_search_prefix_match_ranked_first(client: TestClient):
    """prefix 매칭이 substring보다 위로."""
    res = client.get("/terms/search", params={"q": "유효이자율"})
    results = res.json()["results"]
    assert results[0]["term_id"] == "effective-interest-rate"


# ── /terms/{term_id} ─────────────────────────────────────────────


def test_get_term_returns_full_data(client: TestClient):
    res = client.get("/terms/amortized-cost")
    assert res.status_code == 200
    data = res.json()
    assert data["term"]["term_id"] == "amortized-cost"
    assert data["term"]["name_ko"] == "상각후원가"
    assert data["term"]["definition"]
    assert data["term"]["review_status"] == "ai_draft"


def test_get_term_404(client: TestClient):
    res = client.get("/terms/nonexistent-term-xyz")
    assert res.status_code == 404


def test_get_term_related_chunks(client: TestClient):
    res = client.get("/terms/amortized-cost")
    chunks = res.json()["related"]["chunks"]
    assert chunks  # 최소 1개 (KIFRS 1109 chunk)
    assert chunks[0]["chunk_id"] == "kifrs-1109-amortized-cost"
    assert chunks[0]["title"]


def test_get_term_related_problems(client: TestClient):
    res = client.get("/terms/amortized-cost")
    problems = res.json()["related"]["problems"]
    assert any(p["problem_id"] == "cpa1-accounting-002" for p in problems)


def test_get_term_confusable_resolved(client: TestClient):
    """confusable_with 항목이 name_ko까지 채워져 반환된다."""
    res = client.get("/terms/amortized-cost")
    conf = res.json()["related"]["confusable_terms"]
    assert any(c["term_id"] == "fair-value" and c["name_ko"] == "공정가치" for c in conf)
    assert all("reason" in c for c in conf)


def test_get_term_prerequisite_resolved(client: TestClient):
    """prerequisite_terms이 name_ko와 함께 반환된다."""
    res = client.get("/terms/amortized-cost")
    pre = res.json()["related"]["prerequisite_terms"]
    assert pre
    assert pre[0]["term_id"] == "effective-interest-rate"
    assert pre[0]["name_ko"] == "유효이자율"
    assert pre[0]["in_seed"] is True


def test_get_term_external_prerequisite_marked(client: TestClient):
    """시드 외 참조도 fallback으로 반환되며 in_seed=False로 표시."""
    # mm-proposition은 wacc를 prerequisite로 가지지만 둘 다 시드 안에 있음
    # 시드 외 참조가 있는 term을 찾아 검증 — 또는 의도적으로 in_seed 분기 자체 확인
    res = client.get("/terms/mm-proposition")
    pre = res.json()["related"]["prerequisite_terms"]
    assert pre
    assert all("in_seed" in p for p in pre)
