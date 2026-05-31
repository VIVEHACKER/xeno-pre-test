# 배포 가이드 — CPA First (다중 사용자 · Postgres · 인증)

> 코드는 배포 준비 완료 상태다. 이 문서의 명령은 **당신의 계정/시크릿**으로 직접 실행한다.
> 컨테이너는 동일한 `Dockerfile`을 쓰므로 Render / Fly.io / Railway 어디든 이식된다.

## 0. 공통 — 필수 시크릿

| 변수 | 값 | 비고 |
|---|---|---|
| `ENVIRONMENT` | `prod` | prod면 부팅 시 필수값 검증(fail-fast) |
| `DATABASE_URL` | 관리형 Postgres 연결 문자열 | `postgres://`로 와도 앱이 `postgresql+psycopg://`로 자동 정규화 |
| `JWT_SECRET` | 강한 랜덤 ≥32자 | 생성: `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `CORS_ORIGINS` | 프론트 도메인 (콤마 구분) | same-origin 서빙이면 자기 도메인만. `*` 금지 |
| `COOKIE_SECURE` | `true` | HTTPS 필수 |
| `COOKIE_SAMESITE` | `strict` | |
| `PORT` | 플랫폼 주입값 | 엔트리포인트가 `$PORT` 사용 |
| `SENTRY_DSN` | (선택) | 에러 추적 |

**첫 관리자 만들기**: 최초 1회만 `BOOTSTRAP_FIRST_USER_ADMIN=true`로 배포 → 첫 가입자가 admin →
가입 직후 이 변수를 `false`로 바꿔 재배포. (검수 `/review`는 admin 전용)

마이그레이션은 컨테이너 엔트리포인트(`scripts/docker-entrypoint.sh`)가 Postgres 감지 시
`alembic upgrade head`를 자동 실행한다. Fly는 추가로 `[deploy].release_command`로도 실행.

---

## A. Render (가장 쉬움 — `render.yaml` 블루프린트)

1. GitHub에 브랜치 푸시 후 main 병합 (또는 브랜치 그대로 배포).
2. Render 대시보드 → **New → Blueprint** → 이 레포 선택. `render.yaml`이 자동 인식되어
   웹 서비스 + 관리형 Postgres를 함께 생성한다.
3. `render.yaml`이 자동 주입: `DATABASE_URL`(DB에서), `JWT_SECRET`(generateValue),
   `ENVIRONMENT=prod`, `COOKIE_SECURE=true`. **`CORS_ORIGINS`만 직접 입력** (서비스 도메인).
4. Health check는 `/readyz`로 설정돼 있음. 첫 배포 시 엔트리포인트가 마이그레이션 실행.
5. 검증: `curl https://<your-app>.onrender.com/readyz` → `{"status":"ready","db":true,...}`

---

## B. Fly.io (`fly.toml` 포함)

```bash
# 1) CLI 설치 + 로그인
brew install flyctl && fly auth login

# 2) 앱 생성 (fly.toml 사용; 이름은 본인 것으로)
fly launch --no-deploy --copy-config --name cpa-first-<you>

# 3) 관리형 Postgres 생성 + 연결 (DATABASE_URL 자동 시크릿 주입)
fly postgres create --name cpa-first-db-<you>
fly postgres attach cpa-first-db-<you>

# 4) 시크릿 설정
fly secrets set \
  JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  CORS_ORIGINS="https://cpa-first-<you>.fly.dev" \
  ENVIRONMENT=prod COOKIE_SECURE=true

# 5) 배포 (release_command가 alembic upgrade head 실행)
fly deploy

# 6) 검증
curl https://cpa-first-<you>.fly.dev/readyz
```

`fly.toml`은 health check를 `/readyz`로, 마이그레이션을 release 단계로 분리해 두었다
(`RUN_MIGRATIONS_ON_BOOT=0` → 동시 부팅 시 마이그레이션 레이스 방지).

---

## C. Railway

1. **New Project → Deploy from GitHub repo** → 이 레포 선택. Railway가 `Dockerfile` 자동 감지.
2. **+ New → Database → PostgreSQL** 추가. Railway가 `DATABASE_URL` 변수를 제공.
3. 서비스 Variables에 입력: `ENVIRONMENT=prod`, `JWT_SECRET=<랜덤>`,
   `CORS_ORIGINS=https://<your>.up.railway.app`, `COOKIE_SECURE=true`.
4. 마이그레이션은 컨테이너 엔트리포인트가 기동 시 실행 (Railway는 release 단계가 없으므로
   `RUN_MIGRATIONS_ON_BOOT`을 기본값 1로 둘 것 — fly.toml의 0 설정은 Fly 전용).
5. 검증: `curl https://<your>.up.railway.app/readyz`

---

## 배포 후 스모크 (공통)

```bash
BASE=https://<your-domain>
curl -s $BASE/readyz                                  # {"status":"ready","db":true}
# 회원가입 → access 토큰
TOK=$(curl -s -X POST $BASE/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"me@you.com","password":"<8자 이상>"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
# 진단
curl -s -X POST $BASE/diagnose -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"days_until_exam":60,"available_hours_per_day":5,"current_stage":"mock_exam","subject_states":[{"subject":"accounting","accuracy":0.5,"time_overrun_rate":0.3}]}'
```

## 운영 메모

- **롤백**: 이미지 SHA로 배포되므로 이전 SHA 재배포 = 롤백. GitHub Actions `rollback.yml`(수동 dispatch)에 SHA 입력.
- **관측성**: 구조화 JSON 로그(stdout) → 플랫폼 로그. `/metrics`(Prometheus). `SENTRY_DSN` 설정 시 에러 추적.
- **확장**: 워커 수는 `WEB_CONCURRENCY`(기본 2). KB는 워커별 메모리 로드(읽기전용)라 수평 확장 안전.
- **후속 권장**: 이메일 인증 도입(가입 계정열거 완전 차단), DB 백업 정책, 도메인 커스텀 + HTTPS(플랫폼 자동).
