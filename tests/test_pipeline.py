from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts import cpa_data_pipeline as pipeline

ROOT = Path(__file__).resolve().parents[1]


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


def test_subject_tutorials_cover_all_ontology_subjects_with_solution_paths(tmp_path: Path):
    conn = _connect_memory()

    pipeline.seed_exam_ontology(conn, ROOT / "data" / "seeds" / "exam_ontology.json")
    result = pipeline.seed_subject_tutorials(
        conn,
        ROOT / "data" / "seeds" / "subject_tutorials.json",
        tmp_path / "subject_tutorials.json",
    )

    assert result["subject_tutorials"] == 23
    assert result["tutorial_steps"] == 138
    assert result["solution_concept_links"] == 1656

    missing = conn.execute(
        """
        SELECT s.subject_id
        FROM exam_subjects s
        LEFT JOIN subject_tutorials t ON t.subject_id = s.subject_id
        WHERE t.subject_id IS NULL
        """
    ).fetchall()
    assert missing == []

    weak_steps = conn.execute(
        """
        SELECT step_id
        FROM tutorial_steps
        WHERE json_array_length(solution_paths_json) < 4
        """
    ).fetchall()
    assert weak_steps == []

    weak_paths = conn.execute(
        """
        SELECT step_id
        FROM tutorial_steps
        WHERE EXISTS (
          SELECT 1
          FROM json_each(solution_paths_json)
          WHERE json_extract(value, '$.selection_rationale.why_this_path') IS NULL
             OR json_array_length(json_extract(value, '$.concept_links')) < 3
        )
        """
    ).fetchall()
    assert weak_paths == []


def test_problem_solution_maps_connect_questions_to_concepts_and_eliminations(tmp_path: Path):
    conn = _connect_memory()
    questions = [
        question
        for question in pipeline.load_evaluation_questions(ROOT / "data" / "seeds" / "evaluation")
        if pipeline.safe_problem_for_solution_map(question)
    ]
    expected_question_count = len(questions)
    expected_choice_count = sum(len(question["choices"]) for question in questions)

    result = pipeline.seed_problem_solution_maps(
        conn,
        ROOT / "data" / "seeds" / "evaluation",
        tmp_path / "problem_solution_maps.json",
    )

    assert expected_question_count >= 5
    assert result["problem_solution_maps"] == expected_question_count
    assert result["problem_solution_paths"] == expected_question_count * 4
    assert result["problem_solution_concept_links"] == expected_question_count * 4 * 3
    assert result["problem_choice_eliminations"] == expected_choice_count

    inventory = conn.execute(
        """
        SELECT correct_choice
        FROM problem_solution_maps
        WHERE problem_id = 'cpa1-eval-accounting-002'
        """
    ).fetchone()
    assert inventory["correct_choice"] == 2

    weak_paths = conn.execute(
        """
        SELECT p.path_id
        FROM problem_solution_paths p
        LEFT JOIN problem_solution_concept_links c ON c.path_id = p.path_id
        GROUP BY p.path_id
        HAVING COUNT(c.link_id) < 3
        """
    ).fetchall()
    assert weak_paths == []

    analysis_gaps = conn.execute(
        """
        SELECT problem_id
        FROM problem_solution_maps
        WHERE question_analysis_json IS NULL
           OR json_extract(question_analysis_json, '$.examiner_intent') IS NULL
           OR json_array_length(json_extract(question_analysis_json, '$.stem_conditions')) < 3
           OR json_array_length(json_extract(question_analysis_json, '$.concept_combination')) < 1
        """
    ).fetchall()
    assert analysis_gaps == []

    public_payload = json.loads((tmp_path / "problem_solution_maps.json").read_text(encoding="utf-8"))
    assert all("question_analysis" in item for item in public_payload["problem_solution_maps"])

    choice_paths = conn.execute(
        """
        SELECT
          p.path_id,
          json_array_length(m.choices_json) AS choice_count,
          COUNT(e.elimination_id) AS elimination_count
        FROM problem_solution_paths p
        JOIN problem_solution_maps m ON m.problem_id = p.problem_id
        LEFT JOIN problem_choice_eliminations e ON e.path_id = p.path_id
        WHERE p.path_type = 'choice_elimination'
        GROUP BY p.path_id
        """
    ).fetchall()
    assert len(choice_paths) == expected_question_count
    assert all(row["elimination_count"] == row["choice_count"] for row in choice_paths)


def test_problem_profile_is_specific_for_committed_seed_units():
    questions = {
        question["question_id"]: question
        for question in pipeline.load_evaluation_questions(ROOT / "data" / "seeds" / "evaluation")
    }
    question_ids = [
        "cpa1-eval-accounting-004",
        "cpa1-eval-accounting-005",
        "cpa1-eval-accounting-006",
        "cpa1-eval-accounting-007",
        "cpa1-eval-accounting-008",
        "cpa1-eval-tax-003",
        "cpa1-eval-tax-004",
        "cpa1-eval-tax-005",
    ]

    for question_id in question_ids:
        profile = pipeline.problem_profile(questions[question_id])
        assert profile["core"] != "문제의 핵심 개념", question_id
        assert len(profile["signals"]) >= 3, question_id
