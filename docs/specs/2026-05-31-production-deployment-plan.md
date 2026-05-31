# 프로덕션 배포 전환 계획 (2026-05-31)

> **목표**: 단일 사용자 · 파일 기반 FastAPI 프로토타입 → **다중 사용자 · Postgres · 인증 · 관측성**을 갖춘
> 풀 프로덕션 SaaS. 관리형 PaaS(Docker 기반, 이식 가능) 배포.
>
> 근거: `cpa-prod-readiness-audit` 7차원 감사 (data persistence / multi-user&auth / security /
> config&deps / knowledge-base / frontend / observability&cicd).

## 0. 결정 사항 (Decisions)

| 항목 | 결정 | 근거 |
|---|---|---|
| 사용자 모델 | 다중 사용자 (계정/로그인) | 사용자 선택 |
| 데이터 계층 | 관리형 Postgres (per-user 상태) | 사용자 선택 |
| 지식베이스(KB) | 번들 읽기전용 유지 (Postgres로 옮기지 **않음**) | 큐레이션된 불변 자산. 시작 시 메모리 로드. |
| 배포 | Docker 이미지 (이식 가능) + 1차 타깃 PaaS 선언적 매니페스트 | 락인 회피. 동일 이미지로 Railway/Render/Fly 모두 가능. |
| Python | **3.12** 고정 | asyncpg/argon2 휠 성숙, CI 매트릭스에 이미 존재. (로컬 3.14, pyproject `>=3.11`, CI 3.11/3.12 불일치 해소) |
| ORM/모델 타입 | SQLAlchemy 2.x **sync** + psycopg3 + **이식 가능 타입**(generic `Uuid`/`JSON`/`String`) | 기존 동기 FastAPI 핸들러 + 동기 TestClient(216 테스트)와 정합. 테스트는 in-memory SQLite, 프로덕션은 Postgres(psycopg). citext/jsonb/text[] 미사용 → 양쪽 호환. |
| 마이그레이션 | Alembic (up+down 필수), 배포 시 `alembic upgrade head` (release command) | 백엔드 규칙. 롤백 대비 downgrade 필수. |
| 프론트엔드 | v1은 same-origin StaticFiles 유지 + 인증 UX 추가 | CORS/쿠키 단순화. CDN 분리는 추후. |
| 토큰 전략 | access 15분(메모리), refresh 7일(HttpOnly+Secure+SameSite 쿠키, 서버 회수) | 보안 규칙. XSS 토큰 탈취 최소화. |

## 1. 타깃 아키텍처

```
                    ┌─────────────────────────────────────────┐
  Browser (SPA) ───►│ CORS → RateLimit → Auth → Validation →   │
   access(JWT,mem)  │   Handler → ErrorHandler   (FastAPI)     │
   refresh(cookie)  │                                          │
                    │  ┌── read-only KB (in-memory, startup) ──┐│
                    │  │ rules/problems/terms/edges/rag/maps   ││
                    │  └───────────────────────────────────────┘│
                    │  ┌── per-user state (async SQLAlchemy) ───┐│
                    │  │ users / refresh_tokens / user_state /  ││
                    │  │ prescriptions / mistake_logs /         ││
                    │  │ attempt_diagnoses / review_overrides   ││
                    │  └──────────────┬────────────────────────┘│
                    └─────────────────┼─────────────────────────┘
                                      ▼
                            Managed Postgres (PaaS)
```

- 엔진/RAG/solver 로직은 **불변**. `user_id`의 출처만 request body → JWT subject로 변경.
- KB의 `review_status`는 시드를 덮어쓰지 않고 `review_overrides` DB row로 오버레이.

## 2. 데이터 모델 (Postgres / 이식 가능 타입)

- `users(id Uuid pk, email str unique-ci, password_hash str, role str default 'user', created_at ts)`
- `refresh_tokens(id Uuid pk, user_id fk, token_hash str unique, expires_at ts, revoked_at ts?, created_at ts)`
- `user_state(user_id Uuid pk fk, target_exam, days_until_exam int, available_hours_per_day num, current_stage, subject_states JSON, updated_at ts)`
- `prescriptions(id str pk, user_id fk, generated_at ts, payload JSON, is_active bool)` — 최신 1건 = `is_active`/`generated_at desc`
- `mistake_logs(log_id str, user_id fk, problem_id, attempt_at ts, correct bool, time_seconds int, skipped bool?, mistake_categories JSON, self_note str?, session_id str?, created_at ts, UNIQUE(user_id, log_id))`
- `attempt_diagnoses(attempt_id str pk = uuid, user_id fk, question_id, selected_choice int, time_seconds int?, time_limit_seconds int, created_at ts, diagnosis JSON)`
- `review_overrides(ref_type, ref_id, review_status, reviewer?, updated_at, pk(ref_type, ref_id))`

인덱스: `mistake_logs(user_id, attempt_at)`, `attempt_diagnoses(user_id, created_at)`.

## 3. 엔드포인트 인증 분류

| 분류 | 엔드포인트 |
|---|---|
| PUBLIC | `GET /livez`, `GET /readyz`, `GET /terms/search`, `GET /terms/{id}`, `GET /problems/{id}`, `GET /evidence/{ref_type}/{id}`(KB 타입만), 정적 UI |
| AUTH + per-user | `POST /diagnose`, `GET /prescription`, `POST/GET/DELETE /logs`, `POST /attempts/diagnose`, `GET/DELETE /attempts`, `POST /user-state/refresh`, `GET /evidence/user_state/{id}`(본인만) |
| AUTH (public) | `POST /auth/register`, `POST /auth/login`(5/min), `POST /auth/refresh`, `POST /auth/logout` |
| ADMIN only | `POST /review/{ref_type}/{ref_id}` (+ strict `ref_id` 패턴 `^[A-Za-z0-9_-]+$`) |

요청 바디에서 `user_id` 제거 → 토큰에서 주입.

## 4. 단계별 실행 (Phases)

- **P0 — Foundation**: Python 3.12 고정, 의존성 추가(sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings, argon2-cffi, pyjwt, python-multipart, slowapi, structlog, sentry-sdk[fastapi] opt, prometheus-fastapi-instrumentator, gunicorn). `config.py`(pydantic-settings), 구조화 JSON 로깅, `.env.example` 확장.
- **P1 — DB layer**: `db/`(async engine/session/base), `db/models.py`, Alembic init + 초기 마이그레이션(up/down), 리포지토리. `docker-compose.yml`(app+postgres) 로컬.
- **P2 — Auth**: `auth/`(argon2 해싱, JWT 발급/검증, refresh 회전/회수, `get_current_user`/`get_current_admin`), `/auth/*` 엔드포인트, 로그인 레이트리밋.
- **P3 — Endpoint migration**: `main.py` 영속화 전부 DB로, `user_id` 토큰 주입, `/review` → override 테이블+admin+검증, `/livez`·`/readyz` 분리, 미들웨어 스택(CORS 허용목록·rate limit·보안헤더·TrustedHost·request-id·전역 예외 핸들러 `{error:{code,message}}`), `lifespan`(DB 풀+KB 로드+graceful shutdown).
- **P4 — Frontend auth**: 로그인/회원가입 화면, `apiFetch`(Bearer + 401→refresh→retry), 로그아웃, 상태별 에러 처리, 부팅 시 `GET /prescription` 재수화, 하드코딩 `user_id` 제거, `/attempts/diagnose` API_BASE 정합, `self_note` 이스케이프.
- **P5 — Containerization & infra**: 멀티스테이지 Dockerfile(python:3.12-slim, non-root), `.dockerignore`, PaaS 매니페스트(release command=migrations, health=/readyz, 0.0.0.0:$PORT, gunicorn+uvicorn workers), Sentry/`/metrics`/structured logs.
- **P6 — CI/CD**: ruff+mypy+pytest(coverage)+alembic up/down(postgres service)+docker build, CD(build/push→deploy→migrate→health-gated→rollback), gitleaks.
- **P7 — Verify**: test_api.py 인증/DB 대응(SQLite fixture), auth/repo 테스트 추가, 엔진/rag/solver/term 테스트 그대로 통과, 전체 검증 + 적대적 리뷰.

## 5. 검증 기준 (DoD)

- 전체 테스트 통과(기존 216 유지 + 신규), 커버리지 80%+
- `docker build` 성공, 컨테이너에서 `/readyz` 200(Postgres 연결 시)
- 미인증 요청이 per-user/admin 엔드포인트에서 401/403
- 동시 다중 사용자 격리(IDOR 없음) — 테스트로 증명
- 시드 파일 런타임 무수정(이미지 읽기전용)
- 시크릿 하드코딩 0, 에러 응답에 스택트레이스 누출 0
