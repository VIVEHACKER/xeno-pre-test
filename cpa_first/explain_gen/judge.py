"""해설 품질 judge — 풀이 과정의 논리 정오를 채점한다.

답 번호 일치(answer_match)는 explain_gen.generator가 이미 검증한다.
이 모듈이 잡는 것은 그 다음 축이다: **답은 맞는데 풀이가 틀린**
(right-answer-wrong-reasoning) 해설의 검출. 감사에서 "설명 텍스트 품질을
채점한 실측이 리포 전체에 0건"으로 확인된 갭을 메운다.

원칙:
- judge는 적대적으로 반박을 시도한다 (확증 편향 방지)
- judge 백엔드는 생성 백엔드와 다른 모델을 권장 (자기 채점 편향 회피)
- 채점 결과는 저장하되, fail이어도 해설을 자동 삭제하지 않는다 —
  노출 게이트 조정은 사람이 판단한다 (needs_review 마킹만)
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cpa_first.eval_gen._json_extract import extract_json_object

JUDGMENT_SCHEMA = "explanation_judgment.v1"

JUDGE_SYSTEM_PROMPT = """당신은 한국 공인회계사 1차 시험 해설의 검수위원이다.
주어진 AI 해설의 **풀이 과정**을 적대적으로 검증하라. 최종 답 번호가 정답과
일치한다는 사실은 이미 확인되었다 — 당신의 임무는 답이 아니라 **근거**를 채점하는 것이다.

검증 항목:
1. 논리 오류: 전제→결론 비약, 잘못된 인과, 순환 논증
2. 사실 오류: 틀린 기준서/조문 인용, 틀린 정의, 틀린 수치/계산 과정
3. 우연 정답: 풀이가 틀렸는데 답만 맞은 경우 (가장 중요한 검출 대상)
4. 완결성: 핵심 단계 생략 없이 학습자가 따라갈 수 있는가

반드시 아래 JSON만 출력하라 (다른 텍스트 금지):
{
  "reasoning_correct": true|false,
  "errors": ["발견한 오류 각각 1문장. 없으면 빈 배열"],
  "completeness": 1-5,
  "verdict": "pass"|"fail",
  "one_line": "판정 근거 1문장"
}
verdict 기준: 사실/논리 오류가 하나라도 결론에 영향을 주면 fail.
사소한 표현 문제만 있으면 pass. 확신이 없으면 fail (보수적 채점)."""

JUDGE_USER_TEMPLATE = """[문제]
{stem}

[보기]
{choices_block}

[공식 정답] {correct_choice}번 (0-기반 인덱스)

[검증 대상 AI 해설]
{walkthrough}

위 해설의 풀이 과정을 적대적으로 검증하고 지정된 JSON만 출력하라."""


def judge_explanation(
    record: dict[str, Any],
    question: dict[str, Any],
    invoke: Any,
    *,
    judge_model_label: str = "",
) -> dict[str, Any]:
    """해설 레코드 1건의 풀이 과정을 채점한다.

    invoke: (system, user) -> str LLM 콜백 (cpa_first.llm.make_invoke).
    반환 judgment 레코드는 parse 실패 시 verdict='judge_parse_failed'로 남긴다 —
    조용히 pass 처리하지 않는다 (fail-closed).
    """
    choices_block = "\n".join(f"{i}. {c}" for i, c in enumerate(question["choices"]))
    user = JUDGE_USER_TEMPLATE.format(
        stem=question["stem"],
        choices_block=choices_block,
        correct_choice=question["correct_choice"],
        walkthrough=record["walkthrough"],
    )
    started = time.perf_counter()
    raw = invoke(JUDGE_SYSTEM_PROMPT, user)
    parsed = extract_json_object(raw)

    judgment: dict[str, Any] = {
        "schema": JUDGMENT_SCHEMA,
        "question_id": record["question_id"],
        "subject": record.get("subject"),
        "applicable_year": record.get("applicable_year"),
        "explanation_model": record.get("model"),
        "judge_model": judge_model_label,
        "judged_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "duration_seconds": round(time.perf_counter() - started, 2),
    }
    if not isinstance(parsed, dict) or "verdict" not in parsed:
        judgment.update(
            {
                "verdict": "judge_parse_failed",
                "reasoning_correct": None,
                "errors": [],
                "completeness": None,
                "one_line": "judge 출력 JSON 파싱 실패",
                "raw_tail": raw[-500:] if isinstance(raw, str) else "",
            }
        )
        return judgment

    judgment.update(
        {
            "verdict": parsed.get("verdict"),
            "reasoning_correct": parsed.get("reasoning_correct"),
            "errors": parsed.get("errors") or [],
            "completeness": parsed.get("completeness"),
            "one_line": parsed.get("one_line", ""),
        }
    )
    return judgment


def judgment_path(out_dir: Path | str, record: dict[str, Any]) -> Path:
    year = record.get("applicable_year") or 0
    return Path(out_dir) / str(year) / f"{record['question_id']}.judgment.json"


def run_judge_batch(
    records: list[tuple[dict[str, Any], dict[str, Any]]],
    invoke: Any,
    out_dir: Path | str,
    *,
    judge_model_label: str = "",
    skip_existing: bool = True,
    progress: Any = None,
) -> dict[str, Any]:
    """(record, question) 쌍 배치 채점. 파일 존재 = 완료 체크포인트.

    백엔드 예외는 저장하지 않고 연속 5회면 중단한다 (generator.run_batch와 동일 규율).
    """
    out = Path(out_dir)
    counts: dict[str, int] = {"skipped_existing": 0}
    consecutive_errors = 0
    for i, (record, question) in enumerate(records, start=1):
        path = judgment_path(out, record)
        if skip_existing and path.exists():
            counts["skipped_existing"] += 1
            continue
        try:
            judgment = judge_explanation(
                record, question, invoke, judge_model_label=judge_model_label
            )
        except Exception as exc:  # noqa: BLE001 — 배치는 계속, 단 저장 안 함
            consecutive_errors += 1
            counts["backend_error"] = counts.get("backend_error", 0) + 1
            if progress is not None:
                progress(f"[{i}/{len(records)}] {record['question_id']} → backend_error: {exc}")
            if consecutive_errors >= 5:
                if progress is not None:
                    progress("backend_error 연속 5회 — 중단")
                break
            continue
        consecutive_errors = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(judgment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        counts[judgment["verdict"]] = counts.get(judgment["verdict"], 0) + 1
        if progress is not None:
            progress(
                f"[{i}/{len(records)}] {record['question_id']} → {judgment['verdict']}"
                f" ({judgment.get('one_line', '')[:60]})"
            )
    return counts


def summarize_judgments(judgments_dir: Path | str) -> dict[str, Any]:
    """저장된 채점 전체의 요약 통계 — '설명 품질 실측치'의 단일 출처."""
    base = Path(judgments_dir)
    total = 0
    by_verdict: dict[str, int] = {}
    by_subject: dict[str, dict[str, int]] = {}
    error_samples: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.judgment.json")):
        j = json.loads(path.read_text(encoding="utf-8"))
        total += 1
        v = j.get("verdict", "unknown")
        by_verdict[v] = by_verdict.get(v, 0) + 1
        subj = j.get("subject") or "unknown"
        by_subject.setdefault(subj, {})[v] = by_subject.setdefault(subj, {}).get(v, 0) + 1
        if v == "fail" and len(error_samples) < 20:
            error_samples.append(
                {
                    "question_id": j["question_id"],
                    "errors": j.get("errors", [])[:3],
                    "one_line": j.get("one_line", ""),
                }
            )
    judged = by_verdict.get("pass", 0) + by_verdict.get("fail", 0)
    return {
        "total": total,
        "by_verdict": by_verdict,
        "pass_rate": round(by_verdict.get("pass", 0) / judged, 4) if judged else None,
        "by_subject": by_subject,
        "fail_samples": error_samples,
    }
