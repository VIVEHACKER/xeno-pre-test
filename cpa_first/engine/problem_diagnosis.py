"""Problem-solution-map based attempt diagnosis.

This module turns a user's selected answer into the next actionable study
decision: why the answer failed, which concepts were missing, and which
solution path should be used on the next pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_problem_solution_maps(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return list(payload.get("problem_solution_maps") or [])


def _path_by_type(problem_map: dict[str, Any], path_type: str) -> dict[str, Any]:
    for path in problem_map.get("solution_paths") or []:
        if path.get("path_type") == path_type:
            return path
    raise ValueError(f"solution path not found: {path_type}")


def _choice_elimination(problem_map: dict[str, Any], choice_index: int) -> dict[str, Any] | None:
    path = _path_by_type(problem_map, "choice_elimination")
    for row in path.get("choice_eliminations") or []:
        if row.get("choice_index") == choice_index:
            return row
    return None


def _next_action(correct: bool, slow: bool) -> dict[str, str]:
    if not correct:
        return {
            "action_type": "concept_rebuild",
            "action_text": "선택한 보기와 정답 보기의 조건 차이를 표시하고 같은 개념의 기초-예제-유제 순서로 다시 푼다.",
        }
    if slow:
        return {
            "action_type": "speed_rebuild",
            "action_text": "정답은 맞혔지만 제한 시간을 넘겼으므로 표/구조식으로 조건 분리 시간을 줄인다.",
        }
    return {
        "action_type": "advance_to_variant",
        "action_text": "핵심 개념과 검산이 통과됐으므로 같은 단원의 낮은 난도 변형 문제로 이동한다.",
    }


def diagnose_problem_attempt(
    problem_map: dict[str, Any],
    *,
    selected_choice: int,
    time_seconds: int | None = None,
    time_limit_seconds: int = 120,
) -> dict[str, Any]:
    choices = problem_map.get("choices") or []
    if selected_choice < 0 or selected_choice >= len(choices):
        raise ValueError(f"selected_choice out of range: {selected_choice}")
    if time_seconds is not None and time_seconds < 0:
        raise ValueError("time_seconds must be non-negative")
    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be positive")

    correct_choice = int(problem_map["correct_choice"])
    correct = selected_choice == correct_choice
    slow = time_seconds is not None and time_seconds > time_limit_seconds

    if not correct:
        recommended_path = _path_by_type(problem_map, "choice_elimination")
    elif slow:
        recommended_path = _path_by_type(problem_map, "structure")
    else:
        recommended_path = _path_by_type(problem_map, "reverse_check")

    selected_elimination = _choice_elimination(problem_map, selected_choice)
    missing_links = [] if correct and not slow else list(recommended_path.get("concept_links") or [])

    mistake_tags: list[str] = []
    if not correct:
        mistake_tags.extend(["concept_gap", "distractor_trap"])
    if slow:
        mistake_tags.append("time_pressure")

    focus_concepts = [
        link["concept_label"]
        for link in missing_links[:3]
        if link.get("concept_label")
    ]

    return {
        "question_id": problem_map["question_id"],
        "subject": problem_map["subject"],
        "unit": problem_map["unit"],
        "correct": correct,
        "selected_choice": selected_choice,
        "selected_choice_text": choices[selected_choice],
        "correct_choice": correct_choice,
        "correct_choice_text": choices[correct_choice],
        "time_seconds": time_seconds,
        "time_limit_seconds": time_limit_seconds,
        "time_over_limit": slow,
        "mistake_tags": mistake_tags,
        "selected_choice_elimination": selected_elimination,
        "recommended_path": {
            "path_id": recommended_path["path_id"],
            "path_type": recommended_path["path_type"],
            "label": recommended_path["label"],
            "why_this_path": recommended_path["why_this_path"],
            "ordered_steps": recommended_path.get("ordered_steps") or [],
        },
        "missing_concept_links": missing_links,
        "next_tutorial": {
            "tutorial_id": problem_map.get("tutorial_id"),
            "focus_concepts": focus_concepts,
            "entry_mode": "기초-개념-예제-유제 순서로 재진입",
        },
        "next_action": _next_action(correct, slow),
        "evidence_refs": [
            {
                "ref_type": "problem_solution_map",
                "ref_id": problem_map["question_id"],
                "note": problem_map.get("unit", ""),
            },
            {
                "ref_type": "solution_path",
                "ref_id": recommended_path["path_id"],
                "note": recommended_path.get("label", ""),
            },
        ],
    }
