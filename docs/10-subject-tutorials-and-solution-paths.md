# 과목별 튜토리얼과 다중 풀이 경로

## 목표

CPA/CTA 전 과목을 기초부터 낮은 난도 문제까지 바로 들어갈 수 있게 만든다.

각 과목 튜토리얼은 다음 흐름을 고정한다.

1. 기초
2. 개념
3. 예제
4. 유제
5. 기출문제형 접근
6. 변형문제

## 데이터 원칙

- `data/seeds/subject_tutorials.json`은 자체 생성 입문 튜토리얼이다.
- 학원 해설, 교재 원문, 실제 기출 문항을 베끼지 않는다.
- 기출 단계는 원문 복제가 아니라 `기출형 접근법`과 저난도 자체 예시로 만든다.
- 문제당 여러 풀이 경로를 붙인다.

## 다중 풀이 경로

파이프라인은 각 문제형 단계에 다음 풀이 경로를 생성한다.

- 정석식: 정의, 공식, 조문, 기준을 직접 적용
- 표/구조식: 조건을 칸으로 쪼개 방향을 안정화
- 검산식: 결론을 원문 조건에 다시 넣어 확인
- 객관식은 선택지 제거식 추가
- 주관식은 답안목차식 추가

각 풀이 경로는 다음 판별 근거를 함께 가진다.

- `selection_rationale`: 왜 이 풀이를 쓰는지, 어떤 신호가 보이면 쓰는지, 어떤 신호가 보이면 배제하는지
- `concept_links`: 풀이가 요구하는 단원 앵커, 조건 신호, 보조 개념
- `decision_test`: 이 풀이를 적용해도 되는지 확인하는 질문
- `rejection_test`: 이 풀이를 쓰면 오히려 느려지거나 틀리는 상황
- `confidence`: 현재 근거의 신뢰도. 입문 자체 생성 데이터는 0.72-0.78 수준으로 시작하고 실제 풀이 로그로 보정한다.

이 구조는 문제를 “맞히는 법”만 저장하지 않고, 왜 그 풀이가 그 문제에 붙는지를 검증 가능한 데이터로 남기기 위한 것이다.

## 실행

```powershell
python scripts/cpa_data_pipeline.py tutorials stats
```

전체 갱신:

```powershell
python scripts/cpa_data_pipeline.py all
```

생성 결과:

- SQLite: `subject_tutorials`, `tutorial_steps`
- SQLite: `solution_concept_links`
- 프론트 데이터: `prototype/subject_tutorials.json`
- 매니페스트 지표: `subject_tutorials`, `tutorial_steps`, `solution_paths`, `solution_concept_links`, `solution_rationales`

## 다음 확장

입문 튜토리얼 다음 단계는 문제별 풀이 로그를 붙이는 것이다.

- 풀이 경로별 소요시간
- 오답 원인
- 같은 문제의 대체 풀이 선택률
- 변형 포인트별 정답률
- 합격자 풀이 순서와 비합격자 풀이 순서 차이
