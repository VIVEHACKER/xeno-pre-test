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
