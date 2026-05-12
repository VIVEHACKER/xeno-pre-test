# CPA Expanded Subjects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 재무관리, 기업법, 경제학, 원가관리회계를 first-class coaching, tutorial, evaluation, problem-map, benchmark, and prototype subjects.

**Architecture:** Treat the four new areas as user-facing training subjects while preserving their exam ontology relationships: 재무관리는 CPA 1차 경영학의 재무관리 unit, 원가관리회계는 CPA 1차 회계학의 unit, 기업법 and 경제학 are CPA 1차 subjects. Replace hard-coded `accounting|tax` assumptions with a shared subject registry used by schemas, API validation, aggregation, prescription, evaluation generation, and UI. Every generated problem map must also include a `question_analysis` block that explains examiner intent, concept co-occurrence rationale, and detailed question-stem parsing.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, JSON Schema, SQLite pipeline, static HTML/CSS/JS prototype, pytest.

---

## Current State

- `data/seeds/exam_ontology.json` already has `cpa1_economics`, `cpa1_corporate_law`, `cpa1_business_finance`, and `acct_cost`.
- `data/seeds/subject_tutorials.json` already has broad tutorials for `경제원론`, `기업법`, `재무관리`, and `원가회계`, but the product logic does not expose them as CPA 1차 training subjects.
- `data/schemas/evaluation_question.schema.json`, `data/schemas/problem_intelligence.schema.json`, and `data/schemas/user_state.schema.json` only allow `accounting` and `tax`.
- `cpa_first/api/main.py`, `cpa_first/engine/aggregate.py`, `prototype/app.js`, and many tests hard-code `accounting|tax`.
- `scripts/cpa_data_pipeline.py::tutorial_id_for_question()` and `problem_profile()` only know accounting/tax units, so new subjects would fall back to weak generic solution maps.
- `prototype/problem_solution_maps.json` currently exposes only accounting/tax evaluation questions.

## Subject IDs

Use these canonical product subject ids:

- `accounting`: existing 회계학/재무회계
- `cost_accounting`: 원가관리회계
- `tax`: existing 세법개론
- `finance`: 재무관리
- `corporate_law`: 기업법
- `economics`: 경제학

Keep ontology links in payload metadata:

- `finance` -> `cpa1_business` / `cpa1_business_finance`
- `cost_accounting` -> `cpa1_accounting` / `acct_cost`
- `corporate_law` -> `cpa1_corporate_law`
- `economics` -> `cpa1_economics`

## Files

- Create: `cpa_first/subjects.py`
  - Single source of truth for subject ids, labels, ontology ids, default time limits, and tutorial ids.
- Create: `cpa_first/problem_intent.py`
  - Single source of truth for question intent analysis, stem decomposition, concept-combination rationale, and examiner-objective inference.
- Modify: `data/schemas/evaluation_question.schema.json`
  - Extend `subject.enum`.
- Modify: `data/schemas/problem_intelligence.schema.json`
  - Extend `subject.enum`.
- Modify: `data/schemas/user_state.schema.json`
  - Extend `subject.enum`.
- Modify: `cpa_first/api/main.py`
  - Use shared subject regex/list instead of `^(accounting|tax)$`.
- Modify: `cpa_first/engine/aggregate.py`
  - Aggregate all registered subjects instead of filtering accounting/tax.
- Modify: `cpa_first/engine/prescribe.py`
  - Make `_task_subject()` and rule matching tolerate all registered subjects.
- Modify: `scripts/cpa_data_pipeline.py`
  - Add subject-aware tutorial ids and `problem_profile()` entries for finance, corporate_law, economics, cost_accounting.
  - Add `question_analysis_json` to generated problem solution maps and public prototype JSON.
- Modify: `data/seeds/evaluation/*.evaluation_question.json`
  - Add safe synthetic seed questions for the four subjects.
- Modify: `data/seeds/rag/*.rag_chunk.json`
  - Add compact concept references for new subjects.
- Modify: `prototype/index.html`
  - Add subject controls for the four new subjects in level diagnosis and coaching.
- Modify: `prototype/app.js`
  - Build payload, coach classification, subject filters, and labels from registry-like constants.
  - Render examiner intent, concept-combination rationale, and stem-condition analysis for the selected problem.
- Modify: `prototype/styles.css`
  - Fit six-subject diagnosis controls without feeling like a settings sheet.
- Modify tests:
  - `tests/test_problem_intent.py`
  - `tests/test_api.py`
  - `tests/test_aggregate.py`
  - `tests/test_pipeline.py`
  - `tests/test_problem_diagnosis.py`
  - `tests/test_rag.py`
  - `tests/test_benchmark.py`

---

## Problem Intent Analysis Contract

Every public `problem_solution_maps.json` item must explain not only "how to solve" but also "why the examiner asked it this way."

Add this object to each generated problem map:

```json
{
  "question_analysis": {
    "examiner_intent": "What ability the examiner is testing.",
    "question_type": "calculation | classification | statement_selection | case_application | mixed",
    "asked_output": "The exact output the stem asks for.",
    "concept_combination": [
      {
        "concept": "present value",
        "paired_with": ["effective interest rate", "interest revenue recognition"],
        "why_combined": "The question forces the learner to separate cash coupon from effective-interest revenue.",
        "examiner_objective": "Detect whether the learner understands measurement basis, not just coupon calculation."
      }
    ],
    "stem_conditions": [
      {
        "text": "amortized cost financial asset",
        "role": "trigger",
        "why_it_matters": "This activates the effective-interest method."
      },
      {
        "text": "interest paid annually in arrears",
        "role": "distractor",
        "why_it_matters": "This tempts the learner to choose coupon cash interest instead of accounting revenue."
      }
    ],
    "question_stem_parse": {
      "ask_verb": "calculate",
      "target_entity": "interest revenue",
      "time_scope": "20X1 year-end",
      "negation": false,
      "unit_or_rounding": "round down below won",
      "must_not_miss": ["measurement basis", "effective interest rate", "carrying amount"]
    },
    "intent_hypothesis": {
      "primary": "Test whether the learner selects the correct accounting model before calculating.",
      "secondary": ["Distinguish cash receipt from revenue recognition", "Use carrying amount rather than face value"],
      "confidence": 0.78
    }
  }
}
```

This analysis must be deterministic and rights-safe. It can be inferred from our synthetic/cleared problem stem, concept tags, unit profile, choices, and generated explanation, but must not copy academy commentary or external copyrighted explanations.

### Task 1: Add Shared Subject Registry

**Files:**
- Create: `cpa_first/subjects.py`
- Test: `tests/test_subjects.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_subjects.py`:

```python
from cpa_first.subjects import (
    CPA1_TRAINING_SUBJECTS,
    SUBJECT_IDS,
    subject_label,
    subject_pattern,
    tutorial_id_for_subject,
)


def test_subject_registry_contains_expanded_cpa1_subjects():
    assert SUBJECT_IDS == {
        "accounting",
        "cost_accounting",
        "tax",
        "finance",
        "corporate_law",
        "economics",
    }
    assert CPA1_TRAINING_SUBJECTS["finance"].ontology_unit_id == "cpa1_business_finance"
    assert CPA1_TRAINING_SUBJECTS["cost_accounting"].ontology_unit_id == "acct_cost"


def test_subject_helpers_are_deterministic():
    assert subject_label("corporate_law") == "기업법"
    assert tutorial_id_for_subject("economics") == "tutorial_cpa1_economics"
    assert subject_pattern().startswith("^(")
    assert "cost_accounting" in subject_pattern()
```

- [ ] **Step 2: Run test to verify RED**

Run:

```powershell
pytest tests/test_subjects.py -q
```

Expected: `ModuleNotFoundError: No module named 'cpa_first.subjects'`.

- [ ] **Step 3: Implement registry**

Create `cpa_first/subjects.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubjectInfo:
    subject_id: str
    label: str
    exam_id: str
    ontology_subject_id: str
    ontology_unit_id: str | None
    tutorial_id: str
    default_time_limit_seconds: int


CPA1_TRAINING_SUBJECTS: dict[str, SubjectInfo] = {
    "accounting": SubjectInfo("accounting", "회계", "CPA_1", "cpa1_accounting", "acct_financial", "tutorial_cpa1_accounting", 120),
    "cost_accounting": SubjectInfo("cost_accounting", "원가관리", "CPA_1", "cpa1_accounting", "acct_cost", "tutorial_cpa2_cost_accounting", 120),
    "tax": SubjectInfo("tax", "세법", "CPA_1", "cpa1_tax", None, "tutorial_cpa1_tax", 120),
    "finance": SubjectInfo("finance", "재무관리", "CPA_1", "cpa1_business", "cpa1_business_finance", "tutorial_cpa2_financial_management", 120),
    "corporate_law": SubjectInfo("corporate_law", "기업법", "CPA_1", "cpa1_corporate_law", None, "tutorial_cpa1_corporate_law", 90),
    "economics": SubjectInfo("economics", "경제학", "CPA_1", "cpa1_economics", None, "tutorial_cpa1_economics", 90),
}

SUBJECT_IDS = set(CPA1_TRAINING_SUBJECTS)


def subject_label(subject_id: str) -> str:
    return CPA1_TRAINING_SUBJECTS.get(subject_id, SubjectInfo(subject_id, subject_id, "", "", None, "", 120)).label


def subject_pattern() -> str:
    return "^(" + "|".join(sorted(SUBJECT_IDS)) + ")$"


def tutorial_id_for_subject(subject_id: str) -> str:
    return CPA1_TRAINING_SUBJECTS[subject_id].tutorial_id
```

- [ ] **Step 4: Run test to verify GREEN**

Run:

```powershell
pytest tests/test_subjects.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add cpa_first/subjects.py tests/test_subjects.py
git commit -m "Add CPA subject registry"
```

---

### Task 2: Extend Schemas and API Validation

**Files:**
- Modify: `data/schemas/evaluation_question.schema.json`
- Modify: `data/schemas/problem_intelligence.schema.json`
- Modify: `data/schemas/user_state.schema.json`
- Modify: `cpa_first/api/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing API test**

Add to `tests/test_api.py`:

```python
def test_diagnose_accepts_expanded_subjects(client: TestClient):
    payload = {
        "user_id": "expanded-user",
        "target_exam": "CPA_1",
        "days_until_exam": 120,
        "available_hours_per_day": 7,
        "current_stage": "objective_entry",
        "subject_states": [
            {"subject": "finance", "accuracy": 0.45, "time_overrun_rate": 0.3, "risk_tags": ["formula_gap"]},
            {"subject": "corporate_law", "accuracy": 0.5, "time_overrun_rate": 0.15, "risk_tags": ["memory_decay"]},
            {"subject": "economics", "accuracy": 0.4, "time_overrun_rate": 0.25, "risk_tags": ["concept_gap"]},
            {"subject": "cost_accounting", "accuracy": 0.55, "time_overrun_rate": 0.35, "risk_tags": ["time_pressure"]},
        ],
    }
    response = client.post("/diagnose", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["prescription"]["user_id"] == "expanded-user"
```

- [ ] **Step 2: Run test to verify RED**

Run:

```powershell
pytest tests/test_api.py::test_diagnose_accepts_expanded_subjects -q
```

Expected: HTTP 422 because `SubjectStateIn.subject` only allows accounting/tax.

- [ ] **Step 3: Extend schema enums**

Set `subject.enum` in the three schema files to:

```json
["accounting", "cost_accounting", "tax", "finance", "corporate_law", "economics"]
```

- [ ] **Step 4: Replace API subject regex**

In `cpa_first/api/main.py`, import `subject_pattern`:

```python
from cpa_first.subjects import subject_pattern
```

Change:

```python
subject: str = Field(pattern="^(accounting|tax)$")
```

to:

```python
subject: str = Field(pattern=subject_pattern())
```

- [ ] **Step 5: Run tests**

Run:

```powershell
pytest tests/test_api.py::test_diagnose_accepts_expanded_subjects -q
python -m cpa_first.cli.validate "data/sample/*.json" "data/seeds/**/*.json"
```

Expected: API test passes; schema validation still passes for existing data.

- [ ] **Step 6: Commit**

```powershell
git add data/schemas/evaluation_question.schema.json data/schemas/problem_intelligence.schema.json data/schemas/user_state.schema.json cpa_first/api/main.py tests/test_api.py
git commit -m "Extend validation to expanded CPA subjects"
```

---

### Task 3: Generalize Log Aggregation and Prescription Subject Handling

**Files:**
- Modify: `cpa_first/engine/aggregate.py`
- Modify: `cpa_first/engine/prescribe.py`
- Test: `tests/test_aggregate.py`
- Test: `tests/test_engine.py`

- [ ] **Step 1: Write failing aggregate test**

Add to `tests/test_aggregate.py`:

```python
def test_aggregate_user_state_includes_expanded_subjects():
    problems = [
        {"problem_id": "F1", "subject": "finance", "time_strategy": {"target_seconds": 90, "skip_threshold_seconds": 120, "exam_room_rule": ""}},
        {"problem_id": "L1", "subject": "corporate_law", "time_strategy": {"target_seconds": 60, "skip_threshold_seconds": 90, "exam_room_rule": ""}},
        {"problem_id": "E1", "subject": "economics", "time_strategy": {"target_seconds": 75, "skip_threshold_seconds": 105, "exam_room_rule": ""}},
        {"problem_id": "C1", "subject": "cost_accounting", "time_strategy": {"target_seconds": 90, "skip_threshold_seconds": 120, "exam_room_rule": ""}},
    ]
    logs = [
        _log("F1", False, 130, mistakes=["formula_gap"]),
        _log("L1", True, 70),
        _log("E1", False, 110, mistakes=["concept_gap"]),
        _log("C1", True, 125, mistakes=["time_pressure"]),
    ]
    state = aggregate_user_state(logs, problems, user_id="u", target_exam="CPA_1", days_until_exam=100, available_hours_per_day=7, current_stage="objective_entry")
    subjects = {s["subject"] for s in state["subject_states"]}
    assert subjects == {"finance", "corporate_law", "economics", "cost_accounting"}
```

- [ ] **Step 2: Run test to verify RED**

Run:

```powershell
pytest tests/test_aggregate.py::test_aggregate_user_state_includes_expanded_subjects -q
```

Expected: subject list is empty because aggregate filters to accounting/tax.

- [ ] **Step 3: Generalize aggregation**

In `cpa_first/engine/aggregate.py`, import `SUBJECT_IDS`:

```python
from cpa_first.subjects import SUBJECT_IDS
```

Replace:

```python
if subject in {"accounting", "tax"}:
```

with:

```python
if subject in SUBJECT_IDS:
```

- [ ] **Step 4: Add engine test for task subject**

Add to `tests/test_engine.py`:

```python
def test_prescribe_returns_expanded_subject_task():
    rule = {
        "rule_key": "finance_time_value",
        "rule_name": "재무관리 시간가치 우선",
        "applicable_stages": ["objective_entry"],
        "applicable_subjects": ["finance"],
        "required_risk_tags": ["formula_gap"],
        "action_text": "화폐의 시간가치 계산을 30분 재구축한다.",
        "source_signal_count": 3,
        "confidence": 0.7,
    }
    user_state = {
        "user_id": "u",
        "target_exam": "CPA_1",
        "days_until_exam": 90,
        "available_hours_per_day": 7,
        "current_stage": "objective_entry",
        "subject_states": [
            {"subject": "finance", "accuracy": 0.4, "time_overrun_rate": 0.2, "risk_tags": ["formula_gap"]},
        ],
    }
    rx = prescribe(user_state, [rule], generated_at=FIXED_TS)
    assert rx["daily_tasks"][0]["subject"] == "finance"
```

- [ ] **Step 5: Generalize `_task_subject()`**

In `cpa_first/engine/prescribe.py`, make the function return any directly matched user subject:

```python
matched = [s for s in rule_subjects if s in user_subjects]
if len(matched) == 1:
    return matched[0]
```

Keep `accounting_tax` special case.

- [ ] **Step 6: Run tests**

```powershell
pytest tests/test_aggregate.py tests/test_engine.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add cpa_first/engine/aggregate.py cpa_first/engine/prescribe.py tests/test_aggregate.py tests/test_engine.py
git commit -m "Generalize coaching engine subjects"
```

---

### Task 4: Add Problem Intent and Question-Stem Analysis

**Files:**
- Create: `cpa_first/problem_intent.py`
- Modify: `scripts/cpa_data_pipeline.py`
- Modify: `prototype/index.html`
- Modify: `prototype/app.js`
- Modify: `prototype/styles.css`
- Test: `tests/test_problem_intent.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing intent-analysis tests**

Create `tests/test_problem_intent.py`:

```python
from cpa_first.problem_intent import analyze_question_intent


def test_analyze_question_intent_explains_examiner_objective_and_stem_parts():
    question = {
        "question_id": "q-fin-asset",
        "exam": "CPA_1",
        "subject": "accounting",
        "unit": "financial_assets",
        "stem": "상각후원가 측정 금융자산의 취득원가와 유효이자율이 주어졌을 때 당기 이자수익은 얼마인가?",
        "choices": ["80,000원", "95,026원", "100,000원", "104,974원"],
        "correct_choice": 1,
        "concept_tags": ["amortized_cost", "effective_interest_rate", "interest_revenue"],
    }
    profile = {
        "core": "상각후원가 금융자산의 유효이자율법",
        "signals": ["상각후원가", "유효이자율", "이자수익", "장부금액"],
        "trap": "액면이자를 이자수익으로 고르는 함정",
    }

    analysis = analyze_question_intent(question, profile)

    assert "유효이자율" in analysis["examiner_intent"]
    assert analysis["question_type"] == "calculation"
    assert analysis["question_stem_parse"]["target_entity"] == "이자수익"
    assert analysis["intent_hypothesis"]["confidence"] >= 0.7
    assert {row["role"] for row in analysis["stem_conditions"]} >= {"trigger", "ask", "distractor"}
    assert analysis["concept_combination"][0]["why_combined"]
```

- [ ] **Step 2: Run RED**

```powershell
pytest tests/test_problem_intent.py -q
```

Expected: `ModuleNotFoundError: No module named 'cpa_first.problem_intent'`.

- [ ] **Step 3: Implement deterministic intent analyzer**

Create `cpa_first/problem_intent.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


QUESTION_TYPES = {
    "얼마": "calculation",
    "금액": "calculation",
    "옳은": "statement_selection",
    "옳지 않은": "statement_selection",
    "해당": "classification",
}


def infer_question_type(stem: str) -> str:
    for token, question_type in QUESTION_TYPES.items():
        if token in stem:
            return question_type
    return "mixed"


def infer_target_entity(stem: str, profile: dict) -> str:
    if "이자수익" in stem:
        return "이자수익"
    if "손상차손" in stem:
        return "손상차손"
    for signal in profile.get("signals", []):
        if signal and signal in stem:
            return signal
    return profile.get("core", "정답 판단")


def analyze_question_intent(question: dict, profile: dict) -> dict:
    stem = question["stem"]
    signals = profile.get("signals", [])
    target = infer_target_entity(stem, profile)
    trap = profile.get("trap", "조건 누락 함정")
    core = profile.get("core", "핵심 개념")

    stem_conditions = [
        {"text": signal, "role": "trigger", "why_it_matters": f"{signal} 신호가 {core} 사용 여부를 결정한다."}
        for signal in signals[:2]
        if signal
    ]
    stem_conditions.append({"text": target, "role": "ask", "why_it_matters": "문제가 최종적으로 요구하는 산출물이다."})
    stem_conditions.append({"text": trap, "role": "distractor", "why_it_matters": "출제자가 오답 선택지를 만들기 위해 넣은 혼동 지점이다."})

    return {
        "examiner_intent": f"{core}를 실제 문항 조건에서 식별하고 {target}까지 연결하는 능력을 본다.",
        "question_type": infer_question_type(stem),
        "asked_output": target,
        "concept_combination": [
            {
                "concept": core,
                "paired_with": signals[:3],
                "why_combined": "단일 암기가 아니라 조건 신호, 계산 또는 분류 기준, 오답 함정을 동시에 판별하게 하려는 조합이다.",
                "examiner_objective": f"{target}을 구하기 전에 어떤 개념 체계를 먼저 선택해야 하는지 검증한다.",
            }
        ],
        "stem_conditions": stem_conditions,
        "question_stem_parse": {
            "ask_verb": "calculate" if infer_question_type(stem) == "calculation" else "select",
            "target_entity": target,
            "time_scope": "stem-defined",
            "negation": "아닌" in stem or "옳지 않은" in stem,
            "unit_or_rounding": "stem-defined",
            "must_not_miss": signals[:3],
        },
        "intent_hypothesis": {
            "primary": f"정답 계산 전에 {core}를 선택할 수 있는지 검증한다.",
            "secondary": [f"{trap}을 피하는지 확인한다.", "본문 조건과 보기의 오답 유인을 연결해 판별하게 한다."],
            "confidence": 0.78,
        },
    }
```

- [ ] **Step 4: Persist analysis in pipeline**

In `scripts/cpa_data_pipeline.py`:

- Import `analyze_question_intent`.
- Add `question_analysis_json TEXT NOT NULL` to `problem_solution_maps`.
- Add `question_analysis` to `build_problem_solution_map(question)` after `profile = problem_profile(question)`.
- Insert `json.dumps(item["question_analysis"], ensure_ascii=False)` when seeding SQLite.
- Ensure the public `prototype/problem_solution_maps.json` includes the `question_analysis` object.

- [ ] **Step 5: Extend pipeline test**

Add to `tests/test_pipeline.py` inside `test_problem_solution_maps_connect_questions_to_concepts_and_eliminations()`:

```python
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
```

Also assert the public JSON has the same field:

```python
public_payload = json.loads((tmp_path / "problem_solution_maps.json").read_text(encoding="utf-8"))
assert all("question_analysis" in item for item in public_payload["problem_solution_maps"])
```

- [ ] **Step 6: Add UI rendering**

In `prototype/index.html`, add a compact section under the selected problem:

```html
<section class="problem-intent-panel" aria-labelledby="problemIntentTitle">
  <h3 id="problemIntentTitle">출제 의도</h3>
  <div id="problemIntent"></div>
  <div id="stemConditionList"></div>
</section>
```

In `prototype/app.js`, render:

- `question_analysis.examiner_intent`
- `question_analysis.concept_combination[].why_combined`
- `question_analysis.stem_conditions[]`
- `question_analysis.question_stem_parse.must_not_miss`

Use concise labels: `의도`, `개념 조합`, `본문 신호`, `놓치면 안 되는 조건`.

- [ ] **Step 7: Run tests and browser checks**

```powershell
pytest tests/test_problem_intent.py tests/test_pipeline.py -q
node --check prototype\app.js
```

Browser check on `http://localhost:4173/`:

- Selecting a problem shows examiner intent.
- The UI explains why the concepts appeared together.
- The stem conditions identify ask/trigger/distractor roles.
- The text does not read like copied academy commentary.

- [ ] **Step 8: Commit**

```powershell
git add cpa_first/problem_intent.py scripts/cpa_data_pipeline.py prototype/index.html prototype/app.js prototype/styles.css tests/test_problem_intent.py tests/test_pipeline.py
git commit -m "Add problem intent analysis layer"
```

---

### Task 5: Add Problem Profiles for New Subjects

**Files:**
- Modify: `scripts/cpa_data_pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing pipeline test**

Add to `tests/test_pipeline.py`:

```python
def test_problem_profile_supports_expanded_subject_units():
    examples = [
        {"question_id": "q-fin", "exam": "CPA_1", "subject": "finance", "unit": "time_value", "choices": ["a", "b", "c", "d"], "correct_choice": 0, "concept_tags": ["present_value"], "stem": "현재가치 문제"},
        {"question_id": "q-law", "exam": "CPA_1", "subject": "corporate_law", "unit": "company_organs", "choices": ["a", "b", "c", "d"], "correct_choice": 1, "concept_tags": ["board_resolution"], "stem": "이사회 결의 문제"},
        {"question_id": "q-econ", "exam": "CPA_1", "subject": "economics", "unit": "elasticity", "choices": ["a", "b", "c", "d"], "correct_choice": 2, "concept_tags": ["price_elasticity"], "stem": "탄력성 문제"},
        {"question_id": "q-cost", "exam": "CPA_1", "subject": "cost_accounting", "unit": "standard_cost", "choices": ["a", "b", "c", "d"], "correct_choice": 3, "concept_tags": ["variance_analysis"], "stem": "차이분석 문제"},
    ]
    for question in examples:
        assert pipeline.tutorial_id_for_question(question)
        profile = pipeline.problem_profile(question)
        assert profile["core"] != "문제의 핵심 개념"
        assert len(profile["direct_steps"]) >= 3
        assert len(profile["signals"]) >= 3
```

- [ ] **Step 2: Run test to verify RED**

```powershell
pytest tests/test_pipeline.py::test_problem_profile_supports_expanded_subject_units -q
```

Expected: fails on generic profile/tutorial id.

- [ ] **Step 3: Use subject registry for tutorial ids**

In `scripts/cpa_data_pipeline.py`, import:

```python
from cpa_first.subjects import tutorial_id_for_subject
```

Replace `tutorial_id_for_question()` body:

```python
return tutorial_id_for_subject(question["subject"])
```

If the subject is not registered, return `""`.

- [ ] **Step 4: Add unit profiles**

Add `problem_profile()` branches:

- `time_value`
  - core: `화폐의 시간가치와 현재가치 할인`
  - signals: `["현금흐름", "할인율", "현재가치", "기간"]`
- `capital_budgeting`
  - core: `NPV와 투자안 채택 기준`
  - signals: `["초기투자", "순현금흐름", "할인율", "NPV"]`
- `company_organs`
  - core: `주주총회·이사회·대표이사의 권한 구분`
  - signals: `["주주총회", "이사회", "대표이사", "결의"]`
- `shares_bonds`
  - core: `주식·사채·자본금 절차`
  - signals: `["신주", "사채", "자본금", "절차"]`
- `elasticity`
  - core: `수요의 가격탄력성과 총수입 변화`
  - signals: `["가격 변화", "수요량 변화", "탄력성", "총수입"]`
- `macro_equilibrium`
  - core: `국민소득 균형과 승수`
  - signals: `["소비함수", "투자", "정부지출", "승수"]`
- `standard_cost`
  - core: `표준원가 차이분석`
  - signals: `["표준", "실제", "가격차이", "수량차이"]`
- `relevant_cost`
  - core: `관련원가와 의사결정`
  - signals: `["매몰원가", "증분원가", "기회비용", "특별주문"]`

Each branch must provide `direct_steps`, `structure_steps`, `trap`, and `eliminations`.

- [ ] **Step 5: Run tests**

```powershell
pytest tests/test_pipeline.py::test_problem_profile_supports_expanded_subject_units -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add scripts/cpa_data_pipeline.py tests/test_pipeline.py
git commit -m "Add problem profiles for expanded CPA subjects"
```

---

### Task 6: Add Synthetic Evaluation Questions

**Files:**
- Create: `data/seeds/evaluation/cpa1-eval-finance-001.evaluation_question.json`
- Create: `data/seeds/evaluation/cpa1-eval-finance-002.evaluation_question.json`
- Create: `data/seeds/evaluation/cpa1-eval-corporate_law-001.evaluation_question.json`
- Create: `data/seeds/evaluation/cpa1-eval-corporate_law-002.evaluation_question.json`
- Create: `data/seeds/evaluation/cpa1-eval-economics-001.evaluation_question.json`
- Create: `data/seeds/evaluation/cpa1-eval-economics-002.evaluation_question.json`
- Create: `data/seeds/evaluation/cpa1-eval-cost_accounting-001.evaluation_question.json`
- Create: `data/seeds/evaluation/cpa1-eval-cost_accounting-002.evaluation_question.json`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing coverage test**

Add to `tests/test_pipeline.py`:

```python
def test_evaluation_questions_cover_expanded_subjects():
    questions = pipeline.load_evaluation_questions(ROOT / "data" / "seeds" / "evaluation")
    subjects = {q["subject"] for q in questions if q["rights_status"] in pipeline.PROBLEM_SOLUTION_RIGHTS_ALLOWLIST}
    assert {"finance", "corporate_law", "economics", "cost_accounting"}.issubset(subjects)
```

- [ ] **Step 2: Run RED**

```powershell
pytest tests/test_pipeline.py::test_evaluation_questions_cover_expanded_subjects -q
```

Expected: fails because no safe questions exist for these subjects.

- [ ] **Step 3: Add safe synthetic questions**

Create two `synthetic_seed` questions per subject. Use low-to-mid difficulty only:

- finance:
  - `time_value`: one present value calculation.
  - `capital_budgeting`: one NPV accept/reject.
- corporate_law:
  - `company_organs`: authority/organ classification.
  - `shares_bonds`: new shares/bonds procedure trap.
- economics:
  - `elasticity`: price elasticity and total revenue.
  - `macro_equilibrium`: simple multiplier.
- cost_accounting:
  - `standard_cost`: price/quantity variance.
  - `relevant_cost`: special order/relevant cost classification.

Each file must include:

```json
{
  "exam": "CPA_1",
  "subject": "...",
  "unit": "...",
  "rights_status": "synthetic_seed",
  "review_status": "ai_draft_verified",
  "choices": ["...", "...", "...", "..."],
  "correct_choice": 0,
  "expected_seconds": 120,
  "difficulty": "easy",
  "difficulty_score": 2,
  "bloom_level": "apply",
  "attractor_traps": ["..."]
}
```

- [ ] **Step 4: Validate schemas**

```powershell
python -m cpa_first.cli.validate "data/sample/*.json" "data/seeds/**/*.json"
```

Expected: all files pass.

- [ ] **Step 5: Run coverage test**

```powershell
pytest tests/test_pipeline.py::test_evaluation_questions_cover_expanded_subjects -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add data/seeds/evaluation tests/test_pipeline.py
git commit -m "Add expanded subject evaluation seeds"
```

---

### Task 7: Generate Problem Solution Maps and Prototype Data

**Files:**
- Modify generated: `prototype/problem_solution_maps.json`
- Modify generated: `data/warehouse/manifest.json` only if tracked policy allows; otherwise do not commit runtime warehouse files.
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Update expected pipeline test behavior**

Extend `test_problem_solution_maps_connect_questions_to_concepts_and_eliminations()` to assert the output contains all expanded subjects:

```python
rows = conn.execute("SELECT DISTINCT subject FROM problem_solution_maps").fetchall()
subjects = {row["subject"] for row in rows}
assert {"finance", "corporate_law", "economics", "cost_accounting"}.issubset(subjects)
```

- [ ] **Step 2: Run pipeline**

```powershell
python scripts\cpa_data_pipeline.py problem-solutions stats
```

Expected:

- `problem_solution_maps` increases by at least 8.
- `problem_solution_paths` increases by at least 32.
- `problem_solution_concept_links` increases by at least 96.

- [ ] **Step 3: Run tests**

```powershell
pytest tests/test_pipeline.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```powershell
git add prototype/problem_solution_maps.json tests/test_pipeline.py
git commit -m "Generate solution maps for expanded subjects"
```

---

### Task 8: Add RAG Chunks for New Subjects

**Files:**
- Create: `data/seeds/rag/finance-time-value.rag_chunk.json`
- Create: `data/seeds/rag/corporate-law-organs.rag_chunk.json`
- Create: `data/seeds/rag/economics-elasticity.rag_chunk.json`
- Create: `data/seeds/rag/cost-standard-variance.rag_chunk.json`
- Test: `tests/test_rag.py`

- [ ] **Step 1: Write failing retrieval tests**

Add to `tests/test_rag.py`:

```python
def test_retrieve_expanded_subject_chunks(chunks):
    cases = [
        ("현재가치 할인율 현금흐름", "finance", "finance-time-value"),
        ("이사회 주주총회 대표이사 권한", "corporate_law", "corporate-law-organs"),
        ("가격탄력성 총수입 수요량", "economics", "economics-elasticity"),
        ("표준원가 가격차이 수량차이", "cost_accounting", "cost-standard-variance"),
    ]
    for query, subject, expected in cases:
        hits = retrieve(query, chunks, subject=subject, top_k=1)
        assert hits
        assert hits[0].chunk.chunk_id == expected
```

- [ ] **Step 2: Run RED**

```powershell
pytest tests/test_rag.py::test_retrieve_expanded_subject_chunks -q
```

Expected: fails because chunks do not exist.

- [ ] **Step 3: Add chunks**

Each `rag_chunk` should include compact, rights-safe explanatory content only. Do not copy textbook pages or academy explanations.

- [ ] **Step 4: Validate and test**

```powershell
python -m cpa_first.cli.validate "data/seeds/rag/*.json"
pytest tests/test_rag.py::test_retrieve_expanded_subject_chunks -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add data/seeds/rag tests/test_rag.py
git commit -m "Add RAG chunks for expanded CPA subjects"
```

---

### Task 9: Update Benchmark Coverage

**Files:**
- Modify: `tests/test_benchmark.py`
- Modify if needed: `cpa_first/benchmark/runner.py`

- [ ] **Step 1: Write failing benchmark test**

Add to `tests/test_benchmark.py`:

```python
def test_benchmark_reports_expanded_subjects(tmp_path):
    questions = [
        _question("q-fin", "finance", correct_choice=0),
        _question("q-law", "corporate_law", correct_choice=0),
        _question("q-econ", "economics", correct_choice=0),
        _question("q-cost", "cost_accounting", correct_choice=0),
    ]
    result = run_benchmark(Solver(mode="stub"), questions)
    assert set(result.per_subject) == {"finance", "corporate_law", "economics", "cost_accounting"}
```

- [ ] **Step 2: Run test**

```powershell
pytest tests/test_benchmark.py::test_benchmark_reports_expanded_subjects -q
```

Expected: likely passes if benchmark already groups dynamically. If it passes immediately, keep it as regression coverage.

- [ ] **Step 3: Fix if needed**

If benchmark has hard-coded accounting/tax thresholds, move thresholds to subject registry defaults.

- [ ] **Step 4: Commit**

```powershell
git add tests/test_benchmark.py cpa_first/benchmark/runner.py
git commit -m "Cover expanded subjects in benchmark"
```

---

### Task 10: Update Prototype Controls and Coaching UI

**Files:**
- Modify: `prototype/index.html`
- Modify: `prototype/app.js`
- Modify: `prototype/styles.css`

- [ ] **Step 1: Define UI behavior**

Keep the current proactive coaching direction. Do not add passive “analysis” screens.

The dashboard should show:

- 회계
- 원가관리
- 세법
- 재무관리
- 기업법
- 경제학

Use compact subject rows instead of six oversized sliders if the screen becomes noisy.

- [ ] **Step 2: Replace hard-coded payload**

In `prototype/app.js`, replace:

```js
const SUBJECT_LABEL = { accounting: "회계", tax: "세법", mixed: "혼합" };
```

with:

```js
const SUBJECTS = [
  { id: "accounting", label: "회계" },
  { id: "cost_accounting", label: "원가관리" },
  { id: "tax", label: "세법" },
  { id: "finance", label: "재무관리" },
  { id: "corporate_law", label: "기업법" },
  { id: "economics", label: "경제학" },
];

const SUBJECT_LABEL = Object.fromEntries(SUBJECTS.map((s) => [s.id, s.label]));
```

Build `subject_states` by iterating `SUBJECTS`.

- [ ] **Step 3: Add controls**

In `prototype/index.html`, add a `subject-level-grid` under the diagnosis inputs. Each subject row needs:

- 정답률 slider
- 시간초과 slider
- optional weakness tag display

Avoid a table-like spreadsheet feel. The user should see it as a level diagnosis surface.

- [ ] **Step 4: Generalize coach classification**

In `prototype/app.js`, change `classifyLearner()` to compute:

```js
const weakest = payload.subject_states
  .slice()
  .sort((a, b) => a.accuracy - b.accuracy || b.time_overrun_rate - a.time_overrun_rate)[0];
```

Use `SUBJECT_LABEL[weakest.subject]`.

- [ ] **Step 5: Browser verify**

Use Browser on `http://localhost:4173/`:

- Dashboard shows six subjects.
- `맞춤 코치` shows one weakest subject and one deferred behavior.
- `문제 훈련` subject filter includes `재무관리`, `기업법`, `경제학`, `원가관리`.
- No user-facing “합격수기 분석” or “인터뷰 설계”.

- [ ] **Step 6: Run static checks**

```powershell
node --check prototype\app.js
python C:\Users\gidc111\.codex\skills\impeccable-design\scripts\scan_design_smells.py .
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add prototype/index.html prototype/app.js prototype/styles.css
git commit -m "Expose expanded CPA subjects in coaching UI"
```

---

### Task 11: End-to-End Verification

**Files:**
- No new files unless verification reveals gaps.

- [ ] **Step 1: Run full schema validation**

```powershell
python -m cpa_first.cli.validate "data/sample/*.json" "data/seeds/**/*.json"
```

Expected: all files pass.

- [ ] **Step 2: Run full test suite**

```powershell
pytest
```

Expected: all tests pass.

- [ ] **Step 3: Run pipeline stats**

```powershell
python scripts\cpa_data_pipeline.py problem-solutions stats
```

Expected: counts include expanded subjects and no rights-blocked data enters solution maps.

- [ ] **Step 4: Browser QA**

Open `http://localhost:4173/` and check:

- `맞춤 코치` still feels like automatic coaching, not data analysis.
- `레벨 진단` reflects six-subject state.
- `문제 훈련` works for at least one new subject question.
- Console errors are empty.

- [ ] **Step 5: Final commit if any fixes**

```powershell
git status --short
git add <changed files>
git commit -m "Verify expanded CPA subject rollout"
```

## Rollout Notes

- Do not train on academy explanations or copied textbook/lecture text.
- Keep new evaluation questions `synthetic_seed` until rights-cleared official questions are available.
- Treat finance and cost accounting as first-class product subjects even though ontology maps them under larger CPA 1차 exam subjects.
- Avoid bringing back passive pages like “합격수기 분석.” The user-facing product should expose only automatic coaching decisions.
