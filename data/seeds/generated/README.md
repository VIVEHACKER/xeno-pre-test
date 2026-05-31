# 생성 문항 드래프트 (ai_draft)

이 디렉터리의 `*.evaluation_question.json`은 **LLM(Claude)이 생성하고 별도 LLM이
답을 가린 채 교차검증(cross-check)에 통과한** 문항이다. 스키마(`evaluation_question`)는
검증을 통과했지만 **`review_status: ai_draft`** 이다.

## 중요 — 정답 보증 아님

교차검증 통과는 "출제 LLM과 풀이 LLM이 같은 답에 합의"했다는 뜻일 뿐, **권위 있는 정답이
아니다**. 둘 다 같은 모델 계열이라 같은 오해를 공유할 수 있다(특히 세법은 연도별 개정).

→ **공식 평가셋(`data/seeds/evaluation/`)에 넣지 말 것.** 이 디렉터리는 벤치마크 글롭에
포함되지 않으므로 정식 정답률 측정을 오염시키지 않는다.

## 승격 절차

1. 전문가(회계사/세무사)가 각 문항의 정답·해설·함정을 검수.
2. 통과분만 `review_status`를 `expert_reviewed`로 올리고 `data/seeds/evaluation/`로 이동.
3. `python -m cpa_first.cli.validate "data/seeds/evaluation/*.evaluation_question.json"` 재검증.

생성 방식: README 루트의 "AI 풀이 / 문제 생성" 참조. (출제→검토→교차검증 파이프라인:
`cpa_first/eval_gen/`)
