# 문제풀이 지능 프로토콜

## 1. 목적

AI가 문제를 푼다는 것은 정답을 맞힌다는 뜻이 아니다. 합격자가 시험장에서 문제를 처리하는 사고 과정을 구조화한다는 뜻이다.

각 문제는 아래 질문에 답해야 한다.

1. 이 문제를 풀기 위해 어떤 개념이 필요한가?
2. 문제를 읽을 때 가장 먼저 봐야 할 정보는 무엇인가?
3. 계산은 어떤 순서로 해야 하는가?
4. 시험장에서 몇 초 안에 판단해야 하는가?
5. 함정은 무엇인가?
6. 사용자가 틀렸다면 어떤 원인인가?
7. 같은 개념은 어떻게 변형될 수 있는가?

## 2. 출력 형식

문제풀이 지능 데이터는 다음 구조를 따른다.

```json
{
  "subject": "accounting",
  "unit": "financial_accounting",
  "concept_tags": ["amortized_cost", "effective_interest_rate"],
  "required_concepts": [],
  "solving_entry_point": "",
  "solving_steps": [],
  "trap_patterns": [],
  "time_strategy": "",
  "variant_axes": [],
  "mistake_diagnosis": []
}
```

## 3. 해설과의 차이

일반 해설:

```text
정답은 3번이다. 유효이자율법에 따라 이자수익을 계산하면...
```

문제풀이 지능:

```text
이 문제는 상각후원가 자체보다 '액면이자와 유효이자'를 분리하는지 확인한다.
첫 문장에서 취득시점과 만기를 찾고, 두 번째로 이자 지급 조건을 확인한다.
보기 계산부터 들어가면 손상 또는 처분 조건을 놓칠 가능성이 높다.
90초 안에 계산식이 잡히지 않으면 표시 후 다음 문제로 넘어간다.
```

## 4. 오답 원인 분류

오답은 다음 중 하나 이상으로 분류한다.

- concept_gap: 개념 자체를 모름
- formula_gap: 식을 알고 있지 않음
- condition_miss: 조건 누락
- calculation_error: 단순 계산 실수
- time_pressure: 시간 압박
- distractor_trap: 매력적 오답 선택
- memory_decay: 암기 휘발
- strategy_error: 풀지 말아야 할 문제에 집착

## 5. 회계학 특화 태그

- financial_accounting
- cost_accounting
- government_accounting
- revenue_recognition
- inventory
- financial_assets
- tangible_assets
- liabilities
- equity
- consolidation
- cash_flow
- standard_costing
- cvp_analysis

## 6. 세법개론 특화 태그

- corporate_tax
- income_tax
- vat
- national_tax_basic_act
- tax_procedure
- gross_income
- deductible_expense
- tax_base
- tax_credit
- withholding
- verbal_rule
- calculation_rule

## 7. AI 검수 기준

문제풀이 지능 데이터는 아래 조건을 통과해야 한다.

- 정답만 있고 풀이 경로가 없으면 실패
- 개념 태그가 너무 넓으면 실패
- 시간 전략이 없으면 보완 필요
- 변형 포인트가 없으면 보완 필요
- 근거 없는 출제 예측을 하면 실패
- 세법 적용연도가 없으면 실패

## 8. 샘플 프롬프트

```text
너는 CPA 1차 회계학/세법개론 문제풀이 분석가다.
아래 문제를 풀되, 정답보다 풀이 지능 데이터를 만드는 것이 목적이다.
문제 원문을 재배포하지 말고, 필요한 개념, 풀이 시작점, 조건 처리 순서, 함정, 시간 전략, 변형 가능성, 오답 원인을 JSON으로 작성하라.
근거가 부족한 내용은 추정이라고 표시하라.
```
