from __future__ import annotations

from pathlib import Path

import pytest

from cpa_first.engine.problem_diagnosis import (
    diagnose_problem_attempt,
    load_problem_solution_maps,
)


ROOT = Path(__file__).resolve().parents[1]
MAPS_PATH = ROOT / "prototype" / "problem_solution_maps.json"


@pytest.fixture(scope="module")
def problem_maps() -> dict[str, dict]:
    return {item["question_id"]: item for item in load_problem_solution_maps(MAPS_PATH)}


def test_wrong_choice_returns_choice_elimination_and_missing_concepts(problem_maps: dict[str, dict]):
    problem = problem_maps["cpa1-eval-accounting-002"]

    diagnosis = diagnose_problem_attempt(
        problem,
        selected_choice=1,
        time_seconds=95,
        time_limit_seconds=120,
    )

    assert diagnosis["correct"] is False
    assert diagnosis["selected_choice"] == 1
    assert diagnosis["correct_choice"] == 2
    assert diagnosis["recommended_path"]["path_type"] == "choice_elimination"
    assert diagnosis["selected_choice_elimination"]["choice_index"] == 1
    assert diagnosis["selected_choice_elimination"]["verdict"] == "eliminate"
    assert "concept_gap" in diagnosis["mistake_tags"]
    assert "distractor_trap" in diagnosis["mistake_tags"]
    assert len(diagnosis["missing_concept_links"]) == 3
    assert diagnosis["next_tutorial"]["tutorial_id"] == problem["tutorial_id"]


def test_slow_correct_attempt_recommends_structure_rebuild(problem_maps: dict[str, dict]):
    problem = problem_maps["cpa1-eval-accounting-001"]

    diagnosis = diagnose_problem_attempt(
        problem,
        selected_choice=problem["correct_choice"],
        time_seconds=170,
        time_limit_seconds=120,
    )

    assert diagnosis["correct"] is True
    assert "time_pressure" in diagnosis["mistake_tags"]
    assert diagnosis["recommended_path"]["path_type"] == "structure"
    assert diagnosis["next_action"]["action_type"] == "speed_rebuild"


def test_fast_correct_attempt_advances_to_variant(problem_maps: dict[str, dict]):
    problem = problem_maps["cpa1-eval-tax-001"]

    diagnosis = diagnose_problem_attempt(
        problem,
        selected_choice=problem["correct_choice"],
        time_seconds=70,
        time_limit_seconds=120,
    )

    assert diagnosis["correct"] is True
    assert diagnosis["mistake_tags"] == []
    assert diagnosis["recommended_path"]["path_type"] == "reverse_check"
    assert diagnosis["next_action"]["action_type"] == "advance_to_variant"


def test_invalid_choice_rejected(problem_maps: dict[str, dict]):
    problem = problem_maps["cpa1-eval-tax-001"]

    with pytest.raises(ValueError):
        diagnose_problem_attempt(problem, selected_choice=99)
