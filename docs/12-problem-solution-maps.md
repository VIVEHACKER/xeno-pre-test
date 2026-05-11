# 문제별 풀이 맵

## 목적

문제를 단순 정답/해설로 저장하지 않고, 실제 합격자가 쓰는 풀이 선택 근거까지 데이터로 남긴다.

문제 하나는 다음 구조를 가진다.

- 핵심 개념
- 조건 신호
- 정석식 풀이
- 표/구조식 풀이
- 선택지 제거식 풀이
- 검산식 풀이
- 각 풀이의 사용 조건과 배제 조건
- 보기별 제거 근거

## 권리 원칙

입력은 `evaluation_question` 중 다음 권리 상태만 사용한다.

- `original_sample`
- `synthetic_seed`
- `rights_cleared_past_exam`

학원 해설, 교재 원문, 권리 미확정 기출 원문은 이 맵 생성 입력으로 쓰지 않는다.

## 실행

```powershell
python scripts/cpa_data_pipeline.py problem-solutions stats
```

생성 결과:

- SQLite: `problem_solution_maps`
- SQLite: `problem_solution_paths`
- SQLite: `problem_solution_concept_links`
- SQLite: `problem_choice_eliminations`
- 프론트 데이터: `prototype/problem_solution_maps.json`

## 판별 기준

각 풀이 경로는 다음 질문으로 채택 여부를 판단한다.

- 이 문제의 핵심 개념 신호가 본문에 직접 있는가?
- 조건이 3개 이상 섞여 표/구조식이 필요한가?
- 선택지 중 대표 함정값이 보여 제거식이 유효한가?
- 정답 후보를 원문 조건에 다시 넣어 검산할 수 있는가?

이 레이어가 쌓이면 같은 문제에 대해 빠른 풀이, 안전한 풀이, 실전 배제 풀이를 모두 비교할 수 있다.
