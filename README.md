# CPA First

CPA 1차 회계학/세법개론을 시작점으로 하는 합격 운영체계 기획 산출물입니다.

이 프로젝트의 방향은 단순 기출 통계가 아닙니다. 문제를 실제로 푸는 과정에서 필요한 개념, 풀이 순서, 시간 판단, 함정, 변형 가능성을 구조화하고, 공개 합격수기와 합격자 인터뷰에서 뽑은 암묵지를 사용자 상태에 맞는 공부 처방으로 바꾸는 것입니다.

## 산출물

- [제품 요구사항 문서](docs/01-prd-cpa-first.md)
- [데이터 전략](docs/02-data-strategy.md)
- [합격수기 크롤링 및 인터뷰 설계](docs/03-success-story-and-interview-system.md)
- [전략 엔진 설계](docs/04-strategy-engine.md)
- [문제풀이 지능 프로토콜](docs/05-problem-solving-intelligence.md)
- [실제 데이터 적재 파이프라인](docs/06-data-warehouse-and-pipeline.md)
- [구현 계획](docs/07-implementation-plan.md)
- [CPA/CTA 전 과목 데이터 프로그램](docs/08-cpa-cta-full-scope-data-program.md)
- [기출문제/정답/해설 자산 적재](docs/09-past-exam-and-explanation-assets.md)
- [과목별 튜토리얼과 다중 풀이 경로](docs/10-subject-tutorials-and-solution-paths.md)
- [문제별 풀이맵](docs/12-problem-solution-maps.md)
- [풀이맵 기반 응시 진단](docs/13-attempt-diagnosis.md)
- [데이터 소스 레지스트리](data/source_registry.yaml)
- [초기 원천 URL 시드](data/seeds/cpa_success_sources.csv)
- [CPA/CTA 전 과목 온톨로지](data/seeds/exam_ontology.json)
- [수집 타깃 레지스트리](data/seeds/acquisition_targets.csv)
- [기출/정답/해설 자산 시드](data/seeds/past_exam_assets.csv)
- [과목별 튜토리얼 시드](data/seeds/subject_tutorials.json)
- [문제별 풀이맵 프로토타입 데이터](prototype/problem_solution_maps.json)
- [JSON 스키마](data/schemas) (`term.schema.json`, `term_edge.schema.json` 포함 — 용어 지식 그래프)
- [샘플 문제 지능 데이터](data/sample/cpa_problem_intelligence.example.json)
- [정적 MVP 프로토타입](prototype/index.html)

## 아키텍처 (v0.2 — 다중 사용자 · Postgres · 인증)

`cpa_first` 패키지는 FastAPI 백엔드 + 정적 프론트엔드를 함께 서빙한다. 사용자별 런타임 상태
(진단/처방/오답로그/응시진단)는 **Postgres**에 저장되고, 신원은 **JWT access 토큰(15분) +
HttpOnly refresh 쿠키(7일)**에서만 도출된다(요청 바디에 `user_id` 없음 → IDOR 차단).
지식베이스(decision rules / problems / terms / edges / rag)는 **번들 읽기전용**으로 시작 시
메모리에 로드된다. 자세한 전환 설계는 [`docs/specs/2026-05-31-production-deployment-plan.md`](docs/specs/2026-05-31-production-deployment-plan.md) 참조.

## 로컬 개발

처음 한 번 의존성 설치 (Python 3.12):

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # 기본값은 로컬 SQLite + dev 설정 (DB 불필요)
```

서버 실행 (기본 SQLite, 마이그레이션 불필요):

```bash
python -m cpa_first.api.main --host 127.0.0.1 --port 8000
# 또는: cpa-serve --port 8000
```

Postgres로 개발하려면:

```bash
docker compose up -d db   # 로컬 Postgres
export DATABASE_URL="postgresql+psycopg://cpa:cpa@localhost:5432/cpa"
alembic upgrade head      # 스키마 생성
python -m cpa_first.api.main --port 8000
```

`http://127.0.0.1:8000` 접속 → 로그인/회원가입 후 진단 대시보드. 인증 흐름: 가입 시 access
토큰(메모리) + refresh 쿠키 발급, 401이면 프론트가 자동으로 `/auth/refresh` 후 재시도.

주요 엔드포인트:

- 인증: `POST /auth/register`, `/auth/login`(5/분 제한), `/auth/refresh`, `/auth/logout`, `GET /auth/me`
- 진단: `POST /diagnose`, `GET /prescription`, `POST /user-state/refresh` *(인증 필요)*
  — 처방에 **풀 문항 추천**(`problems_to_solve`/`problems_to_skip`, 이유+근거 포함)과
  **시험일까지 다주차 로드맵**(`study_plan`, 과락 방어 마일스톤 포함)이 채워진다
- 학습 루프: `GET /learning-path?concepts=`(약점 → 선수개념 학습 순서, 인증),
  `GET /tutorials`, `GET /tutorials/{id}`(공개), `GET /practice`(문항 목록·정답 비노출, 커서 페이지네이션),
  `GET /practice/{question_id}`(본문+보기), `POST /practice/{id}/ai-explain`(AI 단계별 풀이, 5/분 제한, 인증)
- 로그/응시: `POST/GET/DELETE /logs`, `POST /attempts/diagnose`(시도 후 공식 해설 반환), `GET/DELETE /attempts` *(인증 필요)*
- 지식그래프(공개): `GET /terms/search`, `GET /terms/{id}`, `GET /problems/{id}`, `GET /evidence/{ref_type}/{id}`
- 검수(admin): `POST /review/{ref_type}/{ref_id}` → `review_overrides` 테이블에 기록(시드 불변)
- 운영: `GET /livez`(liveness), `GET /readyz`(DB 포함 readiness), `GET /metrics`(Prometheus)

## 환경 변수

`.env.example` 참조. 핵심:

| 변수 | 설명 |
|---|---|
| `ENVIRONMENT` | `dev` / `staging` / `prod` / `test` (prod는 부팅 시 필수값 검증) |
| `DATABASE_URL` | `postgresql+psycopg://...` (bare `postgres://`도 자동 정규화). dev 기본은 SQLite |
| `JWT_SECRET` | prod 필수, ≥32자 랜덤 |
| `CORS_ORIGINS` | 콤마 구분 허용목록 (prod에서 `*` 금지). same-origin이면 비움 |
| `COOKIE_SECURE` / `COOKIE_SAMESITE` | refresh 쿠키 플래그 (prod `true`/`strict`) |
| `RATE_LIMIT_LOGIN` / `RATE_LIMIT_DEFAULT` | slowapi 한도 (기본 5/분, 100/분) |
| `AI_EXPLAIN_BACKEND` | AI 풀이 해설 백엔드 (`ollama`/`anthropic`). 미설정 시 `/practice/*/ai-explain` 503 |
| `AI_EXPLAIN_ROUTES` | 과목별 라우팅 override (예: `tax:codex`). 비우면 전 과목 동일 백엔드 |
| `CPA_OLLAMA_MODEL` / `CPA_OLLAMA_NUM_CTX` / `CPA_OLLAMA_NUM_PREDICT` | ollama 백엔드 모델·컨텍스트 (기본 16000/8000 — 미설정 시 reasoning 출력 잘림 방지) |
| `LOG_JSON`, `SENTRY_DSN`, `METRICS_ENABLED` | 관측성 |

## 프로덕션 배포 (Docker → 관리형 PaaS)

이미지 빌드/실행:

```bash
docker compose up --build    # 앱 + Postgres. 엔트리포인트가 alembic upgrade head 후 gunicorn 기동
```

관리형 PaaS:

- **Render**: `render.yaml` 블루프린트 (Docker 웹서비스 + 관리형 Postgres, healthCheck `/readyz`, 마이그레이션은 release/엔트리포인트).
- **Fly.io**: `fly.toml` (`[deploy].release_command = "alembic upgrade head"`, health `/readyz`). `flyctl postgres attach`로 DB 연결 후 `fly secrets set JWT_SECRET=...`.
- **Railway**: 동일 `Dockerfile` 사용 (Postgres 애드온 + 환경변수).

컨테이너는 non-root로 실행되고 코드/시드는 읽기전용, `data/runtime`만 쓰기 가능하다.
CI/CD는 `.github/workflows/ci.yml`(lint·typecheck·pytest·커버리지·alembic up/down·docker build·GHCR push·배포)와
`rollback.yml`(이미지 SHA 재배포)로 구성.

## 검증

```bash
python -m cpa_first.cli.validate "data/sample/*.json" "data/seeds/**/*.json"
pytest -q                     # 248 tests
ruff check cpa_first/config.py cpa_first/logging_config.py cpa_first/ratelimit.py cpa_first/llm.py cpa_first/db cpa_first/auth
mypy                          # 신규 모듈 타입체크
```

## AI 풀이 / 문제 생성 (키 없이)

문제풀이·문항생성은 `invoke(system, user) -> str` 콜백을 통해 LLM 백엔드에 연결된다
(`cpa_first/llm.py`). **Anthropic 키 없이** codex CLI나 로컬 ollama로 동작한다:

```bash
# 결정론(LLM 무관, 6개 공식 유형만 실제 추론):
python -m cpa_first.benchmark.runner --mode reasoned

# codex CLI 백엔드 (codex 자체 인증 사용, 키 불필요. 한 문항당 수십 초 → 배치/오프라인용):
python -m cpa_first.benchmark.runner --backend codex --eval-dir data/seeds/evaluation

# 로컬 ollama 백엔드 (완전 오프라인):
CPA_OLLAMA_MODEL=qwen2.5:32b python -m cpa_first.benchmark.runner --backend ollama

# anthropic (저지연 per-request 운영용, ANTHROPIC_API_KEY 필요):
python -m cpa_first.benchmark.runner --backend anthropic
```

환경변수: `CPA_LLM_BACKEND`(codex|ollama|anthropic), `CPA_LLM_MODEL`, `CPA_OLLAMA_HOST/MODEL`.
서버 solver도 `CPA_SOLVER_MODE=live` + `CPA_LLM_BACKEND`로 동일하게 백엔드를 고른다.

> 참고: codex/ollama 백엔드는 호출당 수십 초로 **배치·오프라인(벤치마크·문항생성·검수)** 에 적합하다.
> 저지연 per-request API 서빙에는 anthropic 백엔드(키)나 호스팅 모델을 권장.

### 교차-모델 앙상블 (최대 정확도/신뢰도)

여러 백엔드로 풀어 **다수결 + 합의 신뢰도**를 산출한다 (`cpa_first/solver/ensemble.py`):

```bash
# 강한 백엔드 먼저(우선순위 tie-break). 다수결 + agreement confidence.
python -m cpa_first.benchmark.runner --backends codex,anthropic --eval-dir data/seeds/evaluation
```

`create_solver(backends=["codex","anthropic"])` → `EnsembleSolver`. 결과의 `tool_calls[0]`에
`agreement`(합의도)·`unanimous`·`backend_answers`가 담겨, **만장일치는 자동 신뢰**하고
**불일치는 인간검토/RAG로 라우팅**할 수 있다.

> 실측(2026-06, KMMLU 실제 기출): 서로 다른 모델(Claude·codex/GPT)이 **합의하면 비-법 과목에서
> ~98% 정답**(자동 신뢰 구간). **단, 법(상법)은 두 모델 오류가 상관돼 합의해도 틀릴 수 있어**
> 앙상블로 못 고친다 → 법은 권위 조문 RAG가 필요. (단일 백엔드는 codex가 Claude보다 강했음.)

### 실전 기출로 재측정 (데이터는 직접 준비)

현재 평가셋(`data/seeds/evaluation/`)은 LLM이 생성한 문항이라 LLM 풀이엔 in-distribution
(낙관적)이다. **실제 기출** 정답률을 보려면 기출을 `evaluation_question` 스키마로 만들어
별도 디렉터리에 넣고 같은 명령으로 돌린다 (코드 변경 불필요):

```bash
# 1) 기출을 data/seeds/past_exam/*.evaluation_question.json 로 작성 (스키마 검증)
python -m cpa_first.cli.validate "data/seeds/past_exam/*.evaluation_question.json"
# 2) 키 없이 codex로 채점
python -m cpa_first.benchmark.runner --backend codex --eval-dir data/seeds/past_exam
```

> 기출 데이터 자체는 저작권·정확성 문제로 리포에 포함하지 않는다. 보유한 기출/정답을
> 스키마에 맞춰 넣으면 보수적(실전 기준) 정답률이 산출된다.

## 초기 제품 정의

> CPA 1차 회계학/세법개론 수험생에게, 합격일까지 남은 시간과 현재 실력을 기준으로 오늘 풀 문제, 복습할 개념, 버릴 유형, 회독 순서를 결정해주는 AI 합격 코치.

## 데이터 적재

합격수기와 시험 전략 자료는 SQLite에 누적합니다.

```powershell
python scripts/cpa_data_pipeline.py all
```

생성되는 파일:

- `data/warehouse/cpa_first.sqlite`
- `data/warehouse/manifest.json`

CPA/CTA 전 과목 온톨로지만 갱신:

```powershell
python scripts/cpa_data_pipeline.py ontology stats
```

기출/정답/해설 자산 갱신:

```powershell
python scripts/cpa_data_pipeline.py exam-assets stats
```

과목별 튜토리얼/풀이 경로 갱신:

```powershell
python scripts/cpa_data_pipeline.py tutorials stats
```

문제별 풀이-개념 연결맵 갱신:

```powershell
python scripts/cpa_data_pipeline.py problem-solutions stats
```

## 핵심 원칙

1. 기출문제는 통계 대상이 아니라 풀이 지능의 원천이다.
2. 합격수기는 감동문이 아니라 의사결정 규칙 데이터다.
3. AI 해설은 정답 설명이 아니라 사용자의 다음 행동을 바꾸는 진단이어야 한다.
4. 합격확률은 마케팅 문구가 아니라 현재 상태의 리스크 지표로 다뤄야 한다.
