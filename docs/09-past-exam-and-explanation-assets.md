# 기출문제/정답/해설 자산 적재

## 핵심 원칙

기출문제와 해설은 같은 권리 상태가 아니다.

- 공식 기출문제/정답: 공식 원천에서 파일 URL, 제목, 첨부명, 해시, 권리 상태를 먼저 쌓는다.
- 학원/출판사 해설: 공개 PDF라도 저작권이 있으므로 권리 확인 또는 제휴 전 학습 데이터로 쓰지 않는다.
- 자체 해설: 공식 문제/정답의 이용 조건을 확인한 뒤, 문제풀이 지능 프로토콜로 생성하고 전문가 검수를 거친다.

## 추가 파일

```text
data/seeds/past_exam_assets.csv
```

기출/정답/해설 원천을 다음 필드로 관리한다.

- `asset_kind`: question, answer, explanation, question_answer
- `source_type`: official, partner_candidate, academy_public_pdf, internal
- `rights_policy`: official_download_check_required, rights_check_required, permission_required, owned_generated_content
- `fetch_policy`: metadata_page, metadata_only, internal_queue
- `training_policy`: train_after_rights_review, do_not_train_until_permission, train_allowed_after_review

권리 가드레일:

- `permission_required`, `rights_check_required`, `license_required`는 CSV에 어떤 `training_policy`가 들어와도 파이프라인에서 `do_not_train_until_permission`으로 강제한다.
- 학원/출판사 해설은 출처를 숨겨 학습하거나 재배포하지 않는다. 제휴 또는 명시 허락이 생기면 별도 권리 상태로 승격한다.
- 실제 풀이 지능은 공식 기출/정답의 권리 검토, 자체 생성 해설, 사용자 풀이 로그, 전문가 검수 데이터로 쌓는다.

## DB 테이블

### past_exam_assets

기출문제, 정답, 해설 원천의 기준 테이블이다.

### asset_documents

공식 상세 페이지 또는 메타데이터 페이지를 fetch한 결과다. 첨부 파일명이 발견되면 `attachment_names_json`에 저장한다. 원문 전체를 서비스에 노출하지 않는다.

### problem_learning_jobs

학습/풀이 작업 큐다.

상태 예:

- `queued_rights_review`: 공식/공개 자산이지만 학습 전 권리 검토 필요
- `blocked`: 허락/제휴/라이선스 전 학습 금지
- `queued_generation`: 자체 해설 생성 대기

## 실행

```powershell
python scripts/cpa_data_pipeline.py exam-assets stats
```

전체 갱신:

```powershell
python scripts/cpa_data_pipeline.py all
```

## 현재 들어간 공식 원천

- Q-Net 세무사 2025년 제62회 1차 문제지
- Q-Net 세무사 2025년 제62회 2차 문제지
- Q-Net 세무사 2024년 제61회 1차 문제지
- Q-Net 세무사 2024년 제61회 2차 문제지
- Q-Net 세무사 정답 공개 페이지
- Q-Net 세무사 2013년 제50회 1차 정답 상세
- 금융감독원 CPA 공식 기출문제 자료실 레지스트리
- 우리경영아카데미 공개 기출/해설 게시글 후보
- 나무경영아카데미 공개 기출/해설 PDF 후보
- 스마트경영아카데미 공개 기출/해설 게시글 후보

## 해설 처리

해설은 다음 세 갈래로 간다.

1. 제휴 해설: 학원/저자/출판사 허락 후 원문 적재 가능
2. 공개 후보 해설: URL과 메타데이터만 저장, 학습은 차단
3. 자체 생성 해설: 문제 지능 데이터와 공식 정답을 바탕으로 생성 후 전문가 검수

이렇게 해야 제품이 커져도 저작권 리스크 없이 문제를 보고 풀고, 풀이 과정을 학습 데이터로 쌓을 수 있다.
