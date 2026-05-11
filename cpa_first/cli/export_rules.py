"""06번 파이프라인의 strategy_rules 테이블을 decision_rule JSON으로 export한다.

이 어댑터는 두 트랙(데이터 적재 ↔ 처방 엔진)을 연결하는 단일 지점이다.
SQL 테이블 컬럼 ↔ decision_rule.schema.json 필드는 일대일이며,
스키마가 추가 정의한 메타 필드(applicable_stages, applicable_subjects,
source_case_ids)는 빈 배열로 두고 M2에서 채운다.

사용 예:
    python -m cpa_first.cli.export_rules
    python -m cpa_first.cli.export_rules --out data/seeds/decision_rules
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "warehouse" / "cpa_first.sqlite"
DEFAULT_OUT_DIR = ROOT / "data" / "seeds" / "decision_rules"

# 06번 SQL이 모르는 수동 메타 필드. export 시 기존 파일에서 보존한다.
MANUAL_META_FIELDS = (
    "applicable_stages",
    "applicable_subjects",
    "required_risk_tags",
    "source_case_ids",
)


def _read_manual_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            existing = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return {key: existing[key] for key in MANUAL_META_FIELDS if key in existing}


def export_rules(db_path: Path, out_dir: Path) -> list[Path]:
    if not db_path.exists():
        raise FileNotFoundError(
            f"SQLite DB not found: {db_path}. 먼저 `python scripts/cpa_data_pipeline.py all` 실행."
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT rule_key, rule_name, condition_text, action_text, exception_text,
               source_signal_count, confidence, review_status
        FROM strategy_rules
        ORDER BY rule_key ASC
        """
    ).fetchall()
    conn.close()

    written: list[Path] = []
    for row in rows:
        path = out_dir / f"{row['rule_key']}.decision_rule.json"
        manual = _read_manual_meta(path)
        rule = {
            "rule_key": row["rule_key"],
            "rule_name": row["rule_name"],
            "condition_text": row["condition_text"],
            "action_text": row["action_text"],
            "exception_text": row["exception_text"],
            "applicable_stages": manual.get("applicable_stages", []),
            "applicable_subjects": manual.get("applicable_subjects", []),
            "required_risk_tags": manual.get("required_risk_tags", []),
            "source_signal_count": int(row["source_signal_count"]),
            "source_case_ids": manual.get("source_case_ids", []),
            "confidence": float(row["confidence"]),
            "review_status": row["review_status"],
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(rule, f, ensure_ascii=False, indent=2)
            f.write("\n")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="strategy_rules → decision_rule JSON 어댑터"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    try:
        written = export_rules(args.db, args.out)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for path in written:
        print(f"wrote {path.relative_to(ROOT)}")
    print(f"\n{len(written)} rule(s) exported to {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
