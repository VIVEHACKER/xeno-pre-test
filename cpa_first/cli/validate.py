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
import sys
from pathlib import Path
from typing import Iterable

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
)

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
    return [_format_error(err) for err in errors]


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
