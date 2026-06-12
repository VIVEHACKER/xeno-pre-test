"""평가셋 일괄 생성 오케스트레이터.

분포 spec → generate_batch → 각 문항 validate_question → write_question.
로그와 통계를 stdout에 출력.

CLI 예:
    python scripts/generate_eval_set.py --plan sample10
    python scripts/generate_eval_set.py --plan full87
    python scripts/generate_eval_set.py --plan sample10 --dry-run   # mock invoke

약점 타겟 생성 (--items: 고정 PLANS 없이 임의 spec, 주어지면 --plan 무시):
    python scripts/generate_eval_set.py --items "tax:corporate_tax:hard:2,accounting:cvp:mid:1"
    python scripts/generate_eval_set.py --items "tax:vat:mid" --dry-run   # count 생략 시 1
    # 형식: "subject:unit:difficulty[:count]"를 쉼표로 연결. 공백 허용.
    # subject는 cpa_first.subjects 등록 과목, difficulty는 easy|mid|hard.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Windows cp949 콘솔에서 한글/원화 출력 깨짐 방지
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

# 프로젝트 루트를 sys.path에 추가 (스크립트 직접 실행 대비)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cpa_first.eval_gen import (  # noqa: E402
    BatchSpec,
    flag_if_questionable,
    generate_batch,
    validate_question,
    write_question,
)
from cpa_first.subjects import SUBJECTS  # noqa: E402

EVAL_DIR = ROOT / "data" / "seeds" / "evaluation"

DIFFICULTIES = ("easy", "mid", "hard")


@dataclass
class GenItem:
    subject: str
    unit: str
    difficulty: str
    count: int


def parse_items(spec: str) -> list[GenItem]:
    """약점 타겟 spec 문자열을 GenItem 목록으로 파싱한다.

    형식: "subject:unit:difficulty[:count]" 항목을 쉼표로 연결한다.
    - count 생략 시 1 (설계 결정: 약점 1건 찌르기가 기본 사용례)
    - 항목/필드 주변 공백 허용, 빈 항목(예: 후행 쉼표)은 무시
    - subject는 cpa_first.subjects의 등록 과목, difficulty는 easy|mid|hard

    이유: 사용자 약점 진단(aggregate.py의 risk_tags/concept_mastery)에 맞춘
    임의 분포를 고정 PLANS 수정 없이 CLI에서 직접 지정하기 위함.
    파싱 에러 메시지에 원본 항목을 그대로 인용해 근거 추적(evidence_refs 호환:
    spec 항목 문자열 자체가 참조 단위)이 가능하다.

    Raises:
        ValueError: 형식 오류·미등록 과목·잘못된 난이도·잘못된 count (한국어 메시지)
    """
    entries = [e.strip() for e in spec.split(",")]
    entries = [e for e in entries if e]
    if not entries:
        raise ValueError("items spec이 비어 있습니다. 예: 'tax:corporate_tax:hard:2'")

    items: list[GenItem] = []
    for entry in entries:
        parts = [p.strip() for p in entry.split(":")]
        if len(parts) not in (3, 4):
            raise ValueError(
                f"잘못된 항목 형식: '{entry}' — 'subject:unit:difficulty[:count]' 형식이어야 합니다"
            )
        subject, unit, difficulty = parts[0], parts[1], parts[2]
        if subject not in SUBJECTS:
            raise ValueError(
                f"미등록 과목: '{subject}' (등록 과목: {', '.join(SUBJECTS)}) — 항목 '{entry}'"
            )
        if not unit:
            raise ValueError(f"unit이 비어 있습니다 — 항목 '{entry}'")
        if difficulty not in DIFFICULTIES:
            raise ValueError(
                f"잘못된 난이도: '{difficulty}' (허용: {'|'.join(DIFFICULTIES)}) — 항목 '{entry}'"
            )
        count = 1
        if len(parts) == 4:
            try:
                count = int(parts[3])
            except ValueError:
                raise ValueError(
                    f"count는 정수여야 합니다: '{parts[3]}' — 항목 '{entry}'"
                ) from None
            if count < 1:
                raise ValueError(f"count는 1 이상이어야 합니다: {count} — 항목 '{entry}'")
        items.append(GenItem(subject, unit, difficulty, count))
    return items


# 10건 샘플 — 사용자 검토용
SAMPLE_10: list[GenItem] = [
    GenItem("accounting", "revenue_recognition", "easy", 1),
    GenItem("accounting", "tangible_assets", "easy", 1),
    GenItem("accounting", "financial_assets", "mid", 1),
    GenItem("accounting", "inventory", "mid", 1),
    GenItem("accounting", "lease", "hard", 1),
    GenItem("accounting", "business_combination", "hard", 1),
    GenItem("tax", "national_tax_basic_act", "easy", 1),
    GenItem("tax", "vat", "mid", 1),
    GenItem("tax", "income_tax", "mid", 1),
    GenItem("tax", "corporate_tax", "hard", 1),
]


# 87건 = 회계 52 + 세법 35 (10건 샘플 별도)
FULL_87: list[GenItem] = [
    # ----- 회계 52건 -----
    # financial_assets +5 (1 existing) → 6
    GenItem("accounting", "financial_assets", "easy", 1),
    GenItem("accounting", "financial_assets", "mid", 2),
    GenItem("accounting", "financial_assets", "hard", 2),
    # inventory +4 → 5
    GenItem("accounting", "inventory", "easy", 1),
    GenItem("accounting", "inventory", "mid", 2),
    GenItem("accounting", "inventory", "hard", 1),
    # tangible_assets +5 → 6
    GenItem("accounting", "tangible_assets", "easy", 1),
    GenItem("accounting", "tangible_assets", "mid", 2),
    GenItem("accounting", "tangible_assets", "hard", 2),
    # intangible_assets +3 → 3
    GenItem("accounting", "intangible_assets", "easy", 1),
    GenItem("accounting", "intangible_assets", "mid", 1),
    GenItem("accounting", "intangible_assets", "hard", 1),
    # revenue_recognition +4 → 5
    GenItem("accounting", "revenue_recognition", "easy", 1),
    GenItem("accounting", "revenue_recognition", "mid", 2),
    GenItem("accounting", "revenue_recognition", "hard", 1),
    # liabilities +4 → 5
    GenItem("accounting", "liabilities", "easy", 1),
    GenItem("accounting", "liabilities", "mid", 2),
    GenItem("accounting", "liabilities", "hard", 1),
    # equity +3 → 4
    GenItem("accounting", "equity", "easy", 1),
    GenItem("accounting", "equity", "mid", 1),
    GenItem("accounting", "equity", "hard", 1),
    # cash_flow +3 → 4
    GenItem("accounting", "cash_flow", "easy", 1),
    GenItem("accounting", "cash_flow", "mid", 1),
    GenItem("accounting", "cash_flow", "hard", 1),
    # cost_management +4 → 5
    GenItem("accounting", "cost_management", "easy", 1),
    GenItem("accounting", "cost_management", "mid", 2),
    GenItem("accounting", "cost_management", "hard", 1),
    # lease +3 → 3
    GenItem("accounting", "lease", "easy", 1),
    GenItem("accounting", "lease", "mid", 1),
    GenItem("accounting", "lease", "hard", 1),
    # income_tax_accounting +3 → 3
    GenItem("accounting", "income_tax_accounting", "easy", 1),
    GenItem("accounting", "income_tax_accounting", "mid", 1),
    GenItem("accounting", "income_tax_accounting", "hard", 1),
    # business_combination +4 → 4
    GenItem("accounting", "business_combination", "easy", 1),
    GenItem("accounting", "business_combination", "mid", 2),
    GenItem("accounting", "business_combination", "hard", 1),
    # financial_instruments +3 → 3
    GenItem("accounting", "financial_instruments", "easy", 1),
    GenItem("accounting", "financial_instruments", "mid", 1),
    GenItem("accounting", "financial_instruments", "hard", 1),
    # eps_diluted +2 → 2
    GenItem("accounting", "eps_diluted", "mid", 1),
    GenItem("accounting", "eps_diluted", "hard", 1),
    # changes_errors +2 → 2
    GenItem("accounting", "changes_errors", "mid", 1),
    GenItem("accounting", "changes_errors", "hard", 1),
    # ----- 세법 35건 -----
    # national_tax_basic_act +4 → 5
    GenItem("tax", "national_tax_basic_act", "easy", 1),
    GenItem("tax", "national_tax_basic_act", "mid", 2),
    GenItem("tax", "national_tax_basic_act", "hard", 1),
    # income_tax +7 → 9
    GenItem("tax", "income_tax", "easy", 1),
    GenItem("tax", "income_tax", "mid", 4),
    GenItem("tax", "income_tax", "hard", 2),
    # corporate_tax +9 → 10
    GenItem("tax", "corporate_tax", "easy", 1),
    GenItem("tax", "corporate_tax", "mid", 5),
    GenItem("tax", "corporate_tax", "hard", 3),
    # vat +6 → 7
    GenItem("tax", "vat", "easy", 1),
    GenItem("tax", "vat", "mid", 3),
    GenItem("tax", "vat", "hard", 2),
    # inheritance_gift_tax +3 → 3
    GenItem("tax", "inheritance_gift_tax", "easy", 1),
    GenItem("tax", "inheritance_gift_tax", "mid", 1),
    GenItem("tax", "inheritance_gift_tax", "hard", 1),
    # international_tax +3 → 3
    GenItem("tax", "international_tax", "easy", 1),
    GenItem("tax", "international_tax", "mid", 1),
    GenItem("tax", "international_tax", "hard", 1),
    # local_tax_etc +3 → 3
    GenItem("tax", "local_tax_etc", "easy", 1),
    GenItem("tax", "local_tax_etc", "mid", 1),
    GenItem("tax", "local_tax_etc", "hard", 1),
]


# 첫 시도에서 009/010 저장 후 인코딩 에러로 중단된 케이스 복구용
SAMPLE_REMAINING_8: list[GenItem] = [
    GenItem("accounting", "financial_assets", "mid", 1),
    GenItem("accounting", "inventory", "mid", 1),
    GenItem("accounting", "lease", "hard", 1),
    GenItem("accounting", "business_combination", "hard", 1),
    GenItem("tax", "national_tax_basic_act", "easy", 1),
    GenItem("tax", "vat", "mid", 1),
    GenItem("tax", "income_tax", "mid", 1),
    GenItem("tax", "corporate_tax", "hard", 1),
]

FULL_ACCOUNTING_52: list[GenItem] = [g for g in FULL_87 if g.subject == "accounting"]
FULL_TAX_35: list[GenItem] = [g for g in FULL_87 if g.subject == "tax"]

# 회계 첫 시도(financial_assets easy/mid/hard 16건까지)에서 API overload로 중단된 케이스 복구용.
# 016까지 저장. inventory부터 끝까지 + financial_assets/hard 보충 1건.
ACCOUNTING_RESUME_AFTER_016: list[GenItem] = [
    GenItem("accounting", "financial_assets", "hard", 1),  # reject 보충
    *[g for g in FULL_ACCOUNTING_52 if g.unit != "financial_assets"],
]

TAX_GAP_8: list[GenItem] = [
    GenItem("tax", "income_tax", "mid", 3),
    GenItem("tax", "income_tax", "hard", 2),
    GenItem("tax", "corporate_tax", "hard", 1),
    GenItem("tax", "inheritance_gift_tax", "hard", 1),
    GenItem("tax", "international_tax", "hard", 1),
]


TAX_GAP_3_RETRY: list[GenItem] = [
    GenItem("tax", "income_tax", "hard", 1),
    GenItem("tax", "inheritance_gift_tax", "hard", 1),
    GenItem("tax", "international_tax", "hard", 1),
]


TAX_GAP_2_RETRY2: list[GenItem] = [
    GenItem("tax", "income_tax", "hard", 1),
    GenItem("tax", "international_tax", "hard", 1),
]


PLANS = {
    "sample10": SAMPLE_10,
    "sample_remaining8": SAMPLE_REMAINING_8,
    "full87": FULL_87,
    "full_accounting_52": FULL_ACCOUNTING_52,
    "full_tax_35": FULL_TAX_35,
    "accounting_resume_after_016": ACCOUNTING_RESUME_AFTER_016,
    "tax_gap_8": TAX_GAP_8,
    "tax_gap_3_retry": TAX_GAP_3_RETRY,
    "tax_gap_2_retry2": TAX_GAP_2_RETRY2,
}


def _mock_invoke_factory() -> Callable[[str, str], str]:
    """오프라인 dry-run용. system 프롬프트 키워드로 generator/validator 분기."""
    import json

    counter = {"n": 0}

    def invoke(system: str, user: str) -> str:
        if "응시자" in system:  # cross_check(답 가린 풀이) prompt
            return "[MOCK] 풀이 근거.\nANSWER: 0"
        if "검토위원" in system:
            return json.dumps(
                {"verdict": "approve", "issues": [], "attractor_traps": ["mock trap"]}
            )
        # generator
        counter["n"] += 1
        i = counter["n"]
        return json.dumps(
            {
                "questions": [
                    {
                        "stem": f"[MOCK] 더미 문항 {i}",
                        "choices": ["A", "B", "C", "D"],
                        "correct_choice": i % 4,
                        "explanation": "mock explanation",
                        "concept_tags": ["mock"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    return invoke


def run_plan(
    plan: list[GenItem],
    invoke: Callable[[str, str], str],
    target_dir: Path,
    *,
    cross_check_invoke: Callable[[str, str], str] | None = None,
) -> dict:
    """생성→검증→저장. cross_check_invoke가 주어지면 '독립 모델'로 정답키를 교차검증한다.

    독립 cross-check이 정답키와 불일치하면 문항을 폐기하지 않고 flagged_questionable로
    표시해 저장한다(독립 모델도 틀릴 수 있으므로 사람 검토 대상으로 남김).
    """
    stats = Counter()
    written: list[Path] = []
    verdict_count = Counter()

    for item in plan:
        spec = BatchSpec(
            subject=item.subject,
            unit=item.unit,
            difficulty=item.difficulty,
            count=item.count,
        )
        print(
            f"[gen] {item.subject:<10} {item.unit:<24} {item.difficulty:<5} x{item.count}",
            flush=True,
        )
        questions = generate_batch(spec, invoke)
        if not questions:
            stats["batch_failed"] += 1
            print("  -> batch failed (no parse)", flush=True)
            continue

        for q in questions[: item.count]:
            vr = validate_question(
                q,
                invoke,
                cross_check=cross_check_invoke is not None,
                cross_check_invoke=cross_check_invoke,
            )
            verdict_count[vr.verdict] += 1
            if vr.verdict == "reject":
                stats["rejected"] += 1
                print(f"  reject: {vr.issues}", flush=True)
                continue
            if vr.verdict == "revise" and vr.revised:
                q.update(vr.revised)
                q["review_status"] = "ai_draft_revised"
            else:
                q["review_status"] = "ai_draft_verified"
            q["attractor_traps"] = vr.attractor_traps

            if flag_if_questionable(q, vr):
                stats["flagged_questionable"] += 1

            path = write_question(q, target_dir)
            written.append(path)
            stats["written"] += 1
            if vr.cross_check_passed is None:
                cc = ""
            elif vr.cross_check_passed:
                cc = " cc✓"
            else:
                cc = f" cc✗(키={q.get('correct_choice')},독립={vr.cross_check_chosen})"
            print(f"  ok: {path.name} (verdict={vr.verdict}{cc})", flush=True)

    return {
        "written": written,
        "stats": dict(stats),
        "verdicts": dict(verdict_count),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", choices=list(PLANS.keys()), required=False, default=None)
    parser.add_argument(
        "--items",
        default=None,
        help=(
            "약점 타겟 spec: 'subject:unit:difficulty[:count],...' "
            "(예: 'tax:corporate_tax:hard:2,accounting:cvp:mid:1'). 주어지면 --plan 무시"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="mock invoke (no API call)")
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=EVAL_DIR,
        help="평가셋 저장 디렉터리 (기본: data/seeds/evaluation)",
    )
    parser.add_argument("--model", default=None, help="anthropic model override")
    parser.add_argument(
        "--cross-check-backend",
        default="codex",
        help="정답키 독립 교차검증 백엔드 (codex|ollama|anthropic). 생성기와 다른 모델 권장. 기본 codex(keyless)",
    )
    parser.add_argument("--cross-check-model", default=None, help="cross-check 모델 override")
    parser.add_argument(
        "--no-cross-check",
        action="store_true",
        help="독립 cross-check 비활성화 (검토위원 verdict만)",
    )
    args = parser.parse_args()

    # --items 우선 (약점 타겟), 없으면 --plan (고정 분포). 둘 다 없으면 에러.
    if args.items:
        try:
            plan = parse_items(args.items)
        except ValueError as e:
            parser.error(str(e))
        plan_label = "items(약점 타겟 spec)"
    elif args.plan:
        plan = PLANS[args.plan]
        plan_label = args.plan
    else:
        parser.error("--plan 또는 --items 중 하나는 지정해야 합니다")

    if args.dry_run:
        invoke = _mock_invoke_factory()
        # dry-run: 같은 mock이 cross_check(응시자) 프롬프트도 처리 → 배선만 점검
        cross_check_invoke = None if args.no_cross_check else invoke
    else:
        from cpa_first.eval_gen._anthropic_invoke import make_anthropic_invoke

        invoke = make_anthropic_invoke(model=args.model or "claude-opus-4-7")
        if args.no_cross_check:
            cross_check_invoke = None
        else:
            from cpa_first.llm import make_invoke

            cross_check_invoke = make_invoke(args.cross_check_backend, model=args.cross_check_model)

    cc_label = "off" if cross_check_invoke is None else f"{args.cross_check_backend}(독립)"
    print(
        f"plan={plan_label} items={len(plan)} target_dir={args.target_dir} cross_check={cc_label}"
    )
    result = run_plan(plan, invoke, args.target_dir, cross_check_invoke=cross_check_invoke)

    print()
    print(f"written  : {len(result['written'])}")
    print(f"verdicts : {result['verdicts']}")
    print(f"stats    : {result['stats']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
