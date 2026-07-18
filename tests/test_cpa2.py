"""2차 주관식 트랙 — 로더 + 읽기전용 API 테스트."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from cpa_first.real_exams import load_cpa2_subjective


def _cpa2_question(qid: str, subject: str = "financial_management", year: int = 2025) -> dict:
    return {
        "question_id": qid,
        "exam": "CPA_2",
        "subject": subject,
        "applicable_year": year,
        "number": 1,
        "points": 20,
        "stem": "투자안 A와 B의 NPV를 구하시오.",
        "sub_questions": ["(물음 1) ...", "(물음 2) ..."],
        "model_answer": None,
        "grading_criteria": None,
        "answer_key_policy": "모범답안·채점기준 비공개(금감원 정책)",
        "review_status": "machine_parsed_raw",
        "rights_status": "official_download_check_required",
        "source": "1-2 재무관리 문제(2025-2).pdf",
    }


def _write_cpa2(tmp_path: Path, year: int, subject: str, items: list[dict]):
    d = tmp_path / "parsed" / str(year)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{subject}.subjective.json").write_text(
        json.dumps(items, ensure_ascii=False), encoding="utf-8"
    )


def test_loader_reads_subjective(tmp_path):
    _write_cpa2(tmp_path, 2025, "financial_management", [_cpa2_question("cpa2-real-2025-fm-q01")])
    _write_cpa2(
        tmp_path, 2024, "audit", [_cpa2_question("cpa2-real-2024-audit-q01", "audit", 2024)]
    )
    items = load_cpa2_subjective(tmp_path)
    assert len(items) == 2
    # 정렬: year 오름차순
    assert items[0]["applicable_year"] == 2024
    assert all(q["model_answer"] is None for q in items)


def test_loader_missing_returns_empty(tmp_path):
    assert load_cpa2_subjective(tmp_path / "none") == []


def test_cpa2_endpoints_serve_and_disclose_limits():
    """실제 시드의 2차 데이터를 서빙하고 답안 비공개 정책을 명시한다."""
    from cpa_first.api.main import create_app
    from cpa_first.config import get_settings

    app = create_app(settings=get_settings())
    client = TestClient(app)

    r = client.get("/cpa2/practice")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 0  # 실제 파싱된 2차 문항 존재
    assert "비공개" in body["answer_key_policy"]
    q0 = body["questions"][0]
    assert q0["subject_name"]  # 한국어명 매핑
    # 목록엔 모범답안 없음 (애초에 없지만 노출 필드에도 없어야)
    assert "model_answer" not in q0

    detail = client.get(f"/cpa2/practice/{q0['question_id']}")
    assert detail.status_code == 200
    dbody = detail.json()
    assert dbody["model_answer"] is None
    assert "미지원" in dbody["note"]

    assert client.get("/cpa2/practice/nonexistent").status_code == 404


def test_health_counts_cpa2():
    from cpa_first.api.main import create_app
    from cpa_first.config import get_settings

    app = create_app(settings=get_settings())
    client = TestClient(app)
    body = client.get("/health").json()
    assert body["cpa2_subjective_questions"] > 0
