"""exam_core 튜토리얼 사실 정확성 judge — 전문가 검수 큐 생성기.

기존 judge.py(객관식 풀이 walkthrough 채점)와 다른 축이다. 이 모듈은
튜토리얼 교습 콘텐츠 자체의 사실·계산·법령 정확성을 채점한다:

- worked_example.model_answer의 계산을 독립 재계산해 대조
- K-IFRS 기준서 번호·법 조문 인용의 정오 검증
- 개념 정의·인과의 사실 오류 검출
- 스텝 간 내부 일관성

원칙 (전문가 검수 보조 도구로서의 정직성):
- 확신 없으면 'pass'가 아니라 'uncertain'으로 — 검수 대상에 남긴다(fail-toward-review).
- judge 자신도 틀릴 수 있으므로 최종 판정이 아니라 우선순위화된 큐를 만든다.
- 스타일·표현은 채점하지 않는다. 사실/계산/법령만.
- 파싱 실패는 조용히 pass 처리하지 않는다(fail-closed).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cpa_first.eval_gen._json_extract import extract_json_object

TUTORIAL_JUDGMENT_SCHEMA = "tutorial_accuracy_judgment.v1"

# 심각도. critical=학습자를 틀리게 가르침, major=중요 오류, minor=사소, uncertain=검수필요.
SEVERITIES = ("critical", "major", "minor", "uncertain")
# 오류 범주.
CATEGORIES = (
    "calculation",  # worked_example 계산 오류
    "standard_citation",  # K-IFRS 기준서 번호 오인용
    "legal_article",  # 법 조문 오인용
    "factual",  # 개념 정의·사실 오류
    "internal_consistency",  # 스텝 간 모순
    "exam_relevance",  # 기출 패턴 오설명
)

TUTORIAL_JUDGE_SYSTEM = """당신은 한국 공인회계사(CPA) 1차 수험 교재의 사실 검수 전문가다.
주어진 AI 초안 튜토리얼(6-step)의 **사실·계산·법령 정확성**을 적대적으로 검증하라.
당신의 목표는 이 초안을 전문가가 검수할 때 '먼저 봐야 할 곳'을 짚어주는 것이다.

검증 방법 (반드시 수행):
1. 계산 재현: worked_example·guided_practice의 model_answer에 계산이 있으면 당신이
   직접 처음부터 다시 계산해 결과가 맞는지 대조하라. 불일치 시 category=calculation.
2. 기준서 검증: K-IFRS 기준서 번호(예: 1109, 1115, 1016, 1012)와 조문 인용이 실제로
   그 내용을 규정하는지 확인하라. 번호가 틀렸으면 올바른 번호를 correction에 적어라.
   category=standard_citation.
3. 법령 검증: 상법·법인세법·소득세법·부가가치세법 조문 번호와 요건이 맞는지.
   category=legal_article.
4. 사실 검증: 개념 정의, 인과관계, 요건이 사실인지. category=factual.
5. 일관성: 스텝 간 서로 모순되는 서술이 없는지. category=internal_consistency.

중요 규율:
- **확신이 없으면 severity='uncertain'으로 남겨라.** 틀렸다고 단정하지 말고 검수 대상에 올려라.
  당신 자신도 기준서 번호를 착각할 수 있다 — 확실한 것만 critical/major로.
- 표현·문체·교육적 완성도는 채점하지 않는다. 사실이 틀린 것만 지적하라.
- 오류가 하나도 없으면 step_findings를 빈 배열로 두고 overall_verdict='clean'.
- correction에는 '무엇이 맞는지'를 구체적으로(올바른 수치/기준서번호/조문) 적어라.

반드시 아래 JSON만 출력하라 (다른 텍스트 금지):
{
  "overall_verdict": "clean|minor_issues|has_errors|serious_errors",
  "worked_example_recomputed": true|false,
  "step_findings": [
    {
      "step_type": "foundation|concept|worked_example|guided_practice|past_exam_bridge|variation",
      "severity": "critical|major|minor|uncertain",
      "category": "calculation|standard_citation|legal_article|factual|internal_consistency|exam_relevance",
      "issue": "무엇이 틀렸는가 1-2문장",
      "correction": "올바른 사실/수치/기준서번호"
    }
  ],
  "expert_review_priority": 1,
  "summary": "전문가에게 주는 1-2문장 요약"
}
overall_verdict 기준: critical 있으면 serious_errors, major 있으면 has_errors,
minor/uncertain만 있으면 minor_issues, 아무것도 없으면 clean.
expert_review_priority: 1(가장 먼저 검수, critical/계산오류 다수) ~ 5(마지막, clean에 가까움)."""


def build_judge_user(tutorial: dict[str, Any]) -> str:
    """튜토리얼 1개를 judge 입력 텍스트로 직렬화. 채점에 불필요한 메타는 뺀다."""
    lines = [
        f"[과목] {tutorial.get('subject_name')} / [주제] {tutorial.get('entry_topic')}",
        f"[온톨로지 노드] {tutorial.get('ontology_node')}",
        f"[제목] {tutorial.get('title')}",
        f"[학습목표] {tutorial.get('objective')}",
        "[개념 원자]",
        *[f"  - {a}" for a in tutorial.get("concept_atoms", [])],
        "",
        "[스텝별 콘텐츠]",
    ]
    for i, step in enumerate(tutorial.get("steps", []), start=1):
        lines += [
            f"--- 스텝 {i}: {step.get('step_type')} ({step.get('title')}), 난이도 {step.get('difficulty')} ---",
            f"설명: {step.get('core_explanation')}",
            f"문제: {step.get('prompt')}",
            f"모범답안: {step.get('model_answer')}",
        ]
    lines.append("\n위 튜토리얼의 사실·계산·법령 정확성을 검증하고 지정된 JSON만 출력하라.")
    return "\n".join(lines)


def _severity_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {s: 0 for s in SEVERITIES}
    for f in findings:
        sev = f.get("severity")
        if sev in counts:
            counts[sev] += 1
    return counts


def judge_tutorial(
    tutorial: dict[str, Any], invoke: Any, *, judge_model_label: str = ""
) -> dict[str, Any]:
    """튜토리얼 1개 채점. 파싱 실패는 verdict='judge_parse_failed'로 남긴다(fail-closed)."""
    started = time.perf_counter()
    raw = invoke(TUTORIAL_JUDGE_SYSTEM, build_judge_user(tutorial))
    parsed = extract_json_object(raw)

    record: dict[str, Any] = {
        "schema": TUTORIAL_JUDGMENT_SCHEMA,
        "tutorial_id": tutorial["tutorial_id"],
        "subject_id": tutorial.get("subject_id"),
        "ontology_node": tutorial.get("ontology_node"),
        "judge_model": judge_model_label,
        "generated_by": tutorial.get("generated_by"),
        "judged_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "duration_seconds": round(time.perf_counter() - started, 2),
    }
    if not isinstance(parsed, dict) or "overall_verdict" not in parsed:
        record.update(
            {
                "overall_verdict": "judge_parse_failed",
                "step_findings": [],
                "severity_counts": {s: 0 for s in SEVERITIES},
                "expert_review_priority": 1,  # 파싱 실패는 사람이 봐야 함
                "summary": "judge 출력 JSON 파싱 실패 — 수동 검토 필요",
                "raw_tail": raw[-500:] if isinstance(raw, str) else "",
            }
        )
        return record

    findings = parsed.get("step_findings") or []
    record.update(
        {
            "overall_verdict": parsed.get("overall_verdict"),
            "worked_example_recomputed": bool(parsed.get("worked_example_recomputed")),
            "step_findings": findings,
            "severity_counts": _severity_counts(findings),
            "expert_review_priority": parsed.get("expert_review_priority", 3),
            "summary": parsed.get("summary", ""),
        }
    )
    return record


def judgment_path(out_dir: Path | str, tutorial_id: str) -> Path:
    return Path(out_dir) / f"{tutorial_id}.tutorial_judgment.json"


def run_tutorial_judge_batch(
    tutorials: list[dict[str, Any]],
    invoke: Any,
    out_dir: Path | str,
    *,
    judge_model_label: str = "",
    skip_existing: bool = True,
    progress: Any = None,
) -> dict[str, Any]:
    """배치 채점. 파일 존재 = 완료 체크포인트. 백엔드 연속 5회 실패 시 중단."""
    out = Path(out_dir)
    counts: dict[str, int] = {"skipped_existing": 0}
    consecutive_errors = 0
    for i, tutorial in enumerate(tutorials, start=1):
        path = judgment_path(out, tutorial["tutorial_id"])
        if skip_existing and path.exists():
            counts["skipped_existing"] += 1
            continue
        try:
            record = judge_tutorial(tutorial, invoke, judge_model_label=judge_model_label)
        except Exception as exc:  # noqa: BLE001 — 배치는 계속, 저장 안 함
            consecutive_errors += 1
            counts["backend_error"] = counts.get("backend_error", 0) + 1
            if progress is not None:
                progress(f"[{i}/{len(tutorials)}] {tutorial['tutorial_id']} → backend_error: {exc}")
            if consecutive_errors >= 5:
                if progress is not None:
                    progress("backend_error 연속 5회 — 중단")
                break
            continue
        consecutive_errors = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        counts[record["overall_verdict"]] = counts.get(record["overall_verdict"], 0) + 1
        if progress is not None:
            progress(
                f"[{i}/{len(tutorials)}] {tutorial['tutorial_id']} → {record['overall_verdict']}"
                f" (P{record['expert_review_priority']}, {sum(record['severity_counts'].values())} findings)"
            )
    return counts


def summarize_tutorial_judgments(judgments_dir: Path | str) -> dict[str, Any]:
    """채점 전체 요약 — 전문가 검수 큐의 단일 출처.

    verdict 분포, 심각도 합계, 과목별 오류율, 그리고 검수 우선순위 순으로 정렬된
    튜토리얼 목록(critical/major 상세 포함)을 반환한다.
    """
    base = Path(judgments_dir)
    records = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(base.glob("*.tutorial_judgment.json"))
    ]
    by_verdict: dict[str, int] = {}
    severity_total = {s: 0 for s in SEVERITIES}
    category_total: dict[str, int] = {}
    by_subject: dict[str, dict[str, int]] = {}
    for r in records:
        by_verdict[r["overall_verdict"]] = by_verdict.get(r["overall_verdict"], 0) + 1
        for s, n in r.get("severity_counts", {}).items():
            severity_total[s] = severity_total.get(s, 0) + n
        for f in r.get("step_findings", []):
            cat = f.get("category", "unknown")
            category_total[cat] = category_total.get(cat, 0) + 1
        subj = r.get("subject_id", "unknown")
        by_subject.setdefault(subj, {}).setdefault(r["overall_verdict"], 0)
        by_subject[subj][r["overall_verdict"]] += 1

    # 검수 큐: priority 오름차순 → critical 많은 순 → tutorial_id
    queue = sorted(
        records,
        key=lambda r: (
            r.get("expert_review_priority", 3),
            -r.get("severity_counts", {}).get("critical", 0),
            -r.get("severity_counts", {}).get("major", 0),
            r["tutorial_id"],
        ),
    )
    review_queue = [
        {
            "tutorial_id": r["tutorial_id"],
            "subject_id": r.get("subject_id"),
            "ontology_node": r.get("ontology_node"),
            "verdict": r["overall_verdict"],
            "priority": r.get("expert_review_priority"),
            "severity_counts": r.get("severity_counts"),
            "summary": r.get("summary", ""),
            "critical_and_major": [
                {
                    "step_type": f.get("step_type"),
                    "severity": f.get("severity"),
                    "category": f.get("category"),
                    "issue": f.get("issue"),
                    "correction": f.get("correction"),
                }
                for f in r.get("step_findings", [])
                if f.get("severity") in ("critical", "major")
            ],
        }
        for r in queue
    ]
    clean = by_verdict.get("clean", 0)
    return {
        "total_judged": len(records),
        "by_verdict": by_verdict,
        "severity_total": severity_total,
        "category_total": category_total,
        "by_subject": by_subject,
        "clean_rate": round(clean / len(records), 4) if records else None,
        "review_queue": review_queue,
    }
