"""JSON 데이터 파일을 스키마로 검증한다.

사용 예:
    python -m cpa_first.cli.validate data/sample/*.json
    python -m cpa_first.cli.validate --schema prescription path/to/file.json

파일명 패턴으로 스키마를 자동 라우팅한다. --schema로 명시할 수도 있다.
하나라도 실패하면 종료 코드 1, 모두 통과하면 0.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "data" / "schemas"

# 파일명 패턴 → 스키마 키 매핑. 첫 매칭 우선.
FILENAME_PATTERNS: tuple[tuple[str, str], ...] = (
    ("problem_intelligence", "problem_intelligence"),
    ("success_case", "success_case"),
    ("user_state", "user_state"),
    ("prescription", "prescription"),
    ("decision_rule", "decision_rule"),
    ("mistake_log", "mistake_log"),
    ("subject_tutorials_exam_core", "subject_tutorials_exam_core"),
    ("subject_tutorials", "subject_tutorials"),
    ("evaluation_question", "evaluation_question"),
    ("rag_chunk", "rag_chunk"),
    ("term_edge", "term_edge"),
    ("term", "term"),
)

# exam_core 의미 검증용 — 분개(차변/대변) 표기가 필수인 재무회계 계열 노드.
JOURNAL_ENTRY_REQUIRED_NODES = {
    "acct_revenue",
    "acct_inventory",
    "acct_ppe",
    "acct_financial_assets",
    "acct_liabilities",
    "acct_equity",
    "acct_income_tax",
    "acct_consolidation",
}

# worked_example에 숫자 계산 과정이 필수가 아닌 서술형 노드(법·경영관리·개념체계·절차).
VERBAL_NODES = {
    "acct_conceptual_framework",
    "cpa1_business_organization",
    "cpa1_business_strategy",
    "cpa1_business_marketing",
    "cpa1_business_operations",
    "cpa1_law_commercial_general",
    "cpa1_law_stock_company",
    "cpa1_law_organs",
    "cpa1_law_financing",
    "cpa1_law_reorganization",
    "cpa1_law_cpa_act",
    "cpa1_law_external_audit",
    "tax_framework",
    "tax_local_and_other",
}

KNOWN_SCHEMAS = {key for _, key in FILENAME_PATTERNS}


def load_schema(schema_key: str) -> dict:
    path = SCHEMA_DIR / f"{schema_key}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"schema not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_schema_key(file_path: Path, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    name = file_path.name.lower()
    for pattern, key in FILENAME_PATTERNS:
        if pattern in name:
            return key
    return None


def validate_file(file_path: Path, schema_key: str) -> list[str]:
    """파일 한 개를 검증. 에러 메시지 리스트 반환(빈 리스트면 통과)."""
    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]

    schema = load_schema(schema_key)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    return [_format_error(err) for err in errors] + _semantic_errors(data, schema_key)


def _ontology_node_ids() -> set[str]:
    path = ROOT / "data" / "seeds" / "exam_ontology.json"
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as f:
        ontology = json.load(f)
    return {
        node[0] for subject in ontology.get("subjects", []) for node in subject.get("nodes", [])
    }


def _real_exam_question_ids() -> set[str]:
    from cpa_first.real_exams import load_real_exam_questions

    base = ROOT / "data" / "real_exams" / "cpa1"
    return {q["question_id"] for q in load_real_exam_questions(base)}


def _exam_core_semantic_errors(data: dict) -> list[str]:
    """exam_core 튜토리얼 의미 검증 — 스키마가 못 잡는 콘텐츠 품질 게이트.

    감사에서 확인된 결핍의 재발 방지: 분개 표기 0개, 계산 없는 worked_example,
    기출 미연결 past_exam_bridge, 온톨로지 비매핑.
    """
    errors: list[str] = []
    ontology_ids = _ontology_node_ids()
    real_ids = _real_exam_question_ids()

    for t_idx, tutorial in enumerate(data.get("tutorials") or []):
        prefix = f"tutorials/{t_idx}({tutorial.get('tutorial_id', '?')})"
        node = tutorial.get("ontology_node", "")
        if ontology_ids and node not in ontology_ids:
            errors.append(f"[{prefix}] ontology_node not in exam_ontology.json: {node!r}")

        steps = {s.get("step_type"): s for s in tutorial.get("steps") or []}
        full_text = json.dumps(tutorial.get("steps") or [], ensure_ascii=False)

        if node in JOURNAL_ENTRY_REQUIRED_NODES:
            if full_text.count("차변") < 2 or full_text.count("대변") < 2:
                errors.append(
                    f"[{prefix}] 재무회계 노드는 차변/대변 분개 표기가 최소 2회 필요 "
                    f"(차변 {full_text.count('차변')}회, 대변 {full_text.count('대변')}회)"
                )

        worked = steps.get("worked_example")
        if worked and node not in VERBAL_NODES:
            answer = str(worked.get("model_answer") or "")
            if not (re.search(r"\d", answer) and ("=" in answer or "→" in answer)):
                errors.append(
                    f"[{prefix}] 계산형 노드의 worked_example.model_answer에 "
                    "숫자 계산 과정(= 또는 →)이 없음"
                )

        bridge = steps.get("past_exam_bridge")
        if bridge is not None:
            related = bridge.get("related_question_ids") or []
            if not related:
                errors.append(f"[{prefix}] past_exam_bridge에 related_question_ids가 비어 있음")
            elif real_ids:
                unknown = [qid for qid in related if qid not in real_ids]
                if unknown:
                    errors.append(
                        f"[{prefix}] past_exam_bridge가 존재하지 않는 기출 ID 참조: {unknown}"
                    )
    return errors


def _semantic_errors(data: dict, schema_key: str) -> list[str]:
    if schema_key == "subject_tutorials_exam_core":
        return _exam_core_semantic_errors(data)
    if schema_key != "evaluation_question":
        return []

    errors: list[str] = []
    choices = data.get("choices")
    correct_choice = data.get("correct_choice")
    if not isinstance(choices, list) or not isinstance(correct_choice, int):
        return errors
    if not 0 <= correct_choice < len(choices):
        return ["[correct_choice] correct_choice must be a valid choices index"]

    correct_answer = data.get("correct_answer")
    if correct_answer is None:
        errors.append("[correct_answer] correct_answer is required for answer-key audits")
    elif correct_answer != choices[correct_choice]:
        errors.append(
            "[correct_answer] correct_answer must equal choices[correct_choice] "
            f"(expected {choices[correct_choice]!r}, got {correct_answer!r})"
        )

    explanation = str(data.get("explanation") or "")
    if "보기 보정 권장" in explanation:
        errors.append("[explanation] explanation contains 보기 보정 권장; fix the choices instead")
    if "보기 중 가장 근접" in explanation or "가장 근접한" in explanation:
        errors.append("[explanation] explanation relies on nearest-choice grading; fix the choices")

    for idx, choice in enumerate(choices):
        if idx == correct_choice:
            continue
        if _explanation_claims_choice_is_answer(explanation, str(choice)):
            errors.append(
                "[explanation] explanation marks a non-correct choice as 정답 "
                f"(choice {idx}: {choice!r})"
            )

    return errors


def _explanation_claims_choice_is_answer(explanation: str, choice: str) -> bool:
    if not explanation or not choice:
        return False
    for segment in re.split(r"(?<=[.!?。])\s+|[\r\n]+", explanation):
        if "정답" in segment and choice in segment:
            return True
    return False


def _format_error(err: ValidationError) -> str:
    path = "/".join(str(p) for p in err.path) or "<root>"
    return f"[{path}] {err.message}"


def expand_paths(patterns: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        # Windows에서 cmd가 glob을 펼치지 않으므로 직접 처리
        matched = glob.glob(pattern)
        if matched:
            paths.extend(Path(p) for p in matched)
        else:
            paths.append(Path(pattern))
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CPA First JSON 데이터 스키마 검증기")
    parser.add_argument(
        "paths",
        nargs="+",
        help="검증할 JSON 파일 경로 또는 glob 패턴.",
    )
    parser.add_argument(
        "--schema",
        choices=sorted(KNOWN_SCHEMAS),
        help="모든 파일에 강제 적용할 스키마 키. 미지정 시 파일명으로 자동 라우팅.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="통과한 파일은 출력하지 않음.",
    )
    args = parser.parse_args(argv)

    files = expand_paths(args.paths)
    if not files:
        print("no files matched", file=sys.stderr)
        return 1

    total_failed = 0
    for path in files:
        if not path.exists():
            print(f"FAIL  {path}  (file not found)")
            total_failed += 1
            continue

        schema_key = resolve_schema_key(path, args.schema)
        if schema_key is None:
            print(
                f"SKIP  {path}  (스키마를 추론할 수 없음. --schema로 명시하거나 "
                f"파일명에 {sorted(KNOWN_SCHEMAS)} 중 하나를 포함하시오)"
            )
            total_failed += 1
            continue

        errors = validate_file(path, schema_key)
        if errors:
            total_failed += 1
            print(f"FAIL  {path}  (schema: {schema_key})")
            for err in errors:
                print(f"      {err}")
        elif not args.quiet:
            print(f"PASS  {path}  (schema: {schema_key})")

    if total_failed:
        print(f"\n{total_failed} file(s) failed", file=sys.stderr)
        return 1
    print(f"\nall {len(files)} file(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
