from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts import cpa_data_pipeline as pipeline


def _connect_memory() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    pipeline.init_db(conn)
    return conn


def test_permission_required_exam_asset_stays_blocked_even_if_seed_requests_training(tmp_path: Path):
    csv_path = tmp_path / "assets.csv"
    csv_path.write_text(
        "\n".join(
            [
                "asset_id,exam_id,phase_id,exam_year,round_label,asset_kind,subject_scope,title,url,source_owner,source_type,rights_policy,fetch_policy,training_policy,priority,notes",
                "academy_asset,CPA,CPA_1,2025,60,explanation,accounting,Academy explanation,https://example.com,Academy,academy_public_page,permission_required,metadata_only,train_after_rights_review,1,blocked",
            ]
        ),
        encoding="utf-8",
    )
    conn = _connect_memory()

    pipeline.seed_past_exam_assets(conn, csv_path)
    pipeline.seed_problem_learning_jobs(conn)

    asset = conn.execute("SELECT training_policy FROM past_exam_assets WHERE asset_id = 'academy_asset'").fetchone()
    job = conn.execute("SELECT status, blocker FROM problem_learning_jobs WHERE asset_id = 'academy_asset'").fetchone()

    assert asset["training_policy"] == "do_not_train_until_permission"
    assert job["status"] == "blocked"
    assert job["blocker"] == "permission_or_license_required_before_training"


def test_owned_generated_exam_asset_can_queue_generation(tmp_path: Path):
    csv_path = tmp_path / "assets.csv"
    csv_path.write_text(
        "\n".join(
            [
                "asset_id,exam_id,phase_id,exam_year,round_label,asset_kind,subject_scope,title,url,source_owner,source_type,rights_policy,fetch_policy,training_policy,priority,notes",
                "internal_asset,CPA_CTA,all,,all,explanation,all,Generated explanations,internal://generated,CPA First,internal,owned_generated_content,internal_queue,train_allowed_after_review,1,owned",
            ]
        ),
        encoding="utf-8",
    )
    conn = _connect_memory()

    pipeline.seed_past_exam_assets(conn, csv_path)
    pipeline.seed_problem_learning_jobs(conn)

    job = conn.execute("SELECT status, blocker FROM problem_learning_jobs WHERE asset_id = 'internal_asset'").fetchone()

    assert job["status"] == "queued_generation"
    assert job["blocker"] is None
