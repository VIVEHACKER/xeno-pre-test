# 풀이맵 기반 응시 진단

## 목적

문제 풀이맵을 단순 조회 데이터로 두지 않고, 실제 응시 기록을 쌓는 진단 레이어로 사용한다.

사용자가 한 문제에서 고른 보기와 풀이 시간을 입력하면 다음 항목을 반환한다.

- 정오답
- 선택한 보기의 제거 근거
- 오답 또는 지연의 원인 태그
- 다시 써야 할 풀이 경로
- 필요한 개념 연결
- 다음 튜토리얼 진입점
- 누적 가능한 응시 진단 로그

## API

```powershell
POST /attempts/diagnose
GET /attempts
DELETE /attempts
```

요청 예시:

```json
{
  "attempt_id": "attempt-1",
  "user_id": "active-user",
  "question_id": "cpa1-eval-accounting-002",
  "selected_choice": 1,
  "time_seconds": 95
}
```

응답의 핵심 필드:

- `diagnosis.correct`
- `diagnosis.mistake_tags`
- `diagnosis.selected_choice_elimination`
- `diagnosis.recommended_path`
- `diagnosis.missing_concept_links`
- `diagnosis.next_tutorial`
- `diagnosis.next_action`

## 저장 정책

진단 결과는 `data/runtime/attempt_diagnoses.jsonl`에 JSONL로 누적한다. 이 파일은 개인 런타임 데이터이므로 시드 데이터가 아니라 실제 사용 로그에 해당한다.

## 프로토타입

`문제 지능` 탭에서 내 선택과 풀이 시간을 입력하면 즉시 진단한다.

- FastAPI 서버로 접속한 경우: `/attempts/diagnose`에 기록된다.
- 정적 서버로 접속한 경우: 같은 로직을 브라우저에서 로컬 미리보기로 실행한다.
