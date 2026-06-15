"""프로토타입 UI 실브라우저 시각 검증 (Playwright, 임시 — git 미커밋 권장).

로컬 서버(별도 기동)에 접속해 회원가입→진단→처방→문제풀이→학습로드맵 경로를
클릭하며 콘솔 에러를 수집하고 각 단계 스크린샷을 저장한다.

사용:
    # 1) 서버 먼저 기동(다른 셸):
    ENVIRONMENT=test DATABASE_URL="sqlite+pysqlite:///./data/runtime/ui_pw.sqlite3" \
      RATE_LIMIT_ENABLED=false COOKIE_SECURE=false JWT_SECRET="pw-secret-0123456789-0123456789" \
      .venv/bin/python -m uvicorn cpa_first.api.main:app --port 8155
    # 2) 검증:
    .venv/bin/python scripts/ui_visual_check.py --base http://127.0.0.1:8155 --out /tmp/ui_shots
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DIAGNOSE_FILL = {
    # interview(레벨 진단) 뷰의 과목 입력은 앱마다 다르니, 가장 안정적인 경로:
    # 콘솔에서 직접 triggerDiagnose를 호출하지 않고, 실제 UI 입력을 시뮬레이트하기
    # 어려우면 window 헬퍼를 통해 진단을 트리거한다(앱이 노출 시).
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8155")
    ap.add_argument("--out", default="/tmp/ui_shots")
    ap.add_argument("--email", default="pw@test.com")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    console_errors: list[str] = []
    page_errors: list[str] = []
    results: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on(
            "console",
            lambda m: (
                console_errors.append(f"{m.type}: {m.text}")
                if m.type in ("error", "warning")
                else None
            ),
        )
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        page.goto(args.base, wait_until="networkidle")
        page.screenshot(path=str(out / "01-landing.png"))
        results.append(f"landing 로드: title={page.title()!r}")

        # 회원가입 (로그인 게이트). #authToggleBtn로 가입 모드 전환 후 제출.
        try:
            page.wait_for_selector("#authGate:not([hidden])", timeout=4000)
            page.locator("#authToggleBtn").click()  # 로그인→회원가입 모드
            page.wait_for_timeout(300)
            page.locator("#authEmail").fill(args.email)
            page.locator("#authPassword").fill("supersecret1")
            page.locator("#authSubmit").click()
            # 가입 성공 시 게이트가 사라진다
            page.wait_for_selector("#authGate[hidden]", timeout=6000)
            results.append("회원가입 성공 — 게이트 닫힘")
        except Exception as exc:  # noqa: BLE001
            err = page.locator("#authError")
            detail = err.inner_text() if err.count() else ""
            results.append(f"auth 처리 실패: {exc} | authError={detail!r}")
        page.screenshot(path=str(out / "02-after-auth.png"))

        # 진단 트리거: 레벨 진단 뷰로 이동해 과목 입력이 있으면 채우고, 앱이
        # window.triggerDiagnose를 노출하면 직접 호출(가장 견고).
        triggered = page.evaluate(
            """() => {
                if (typeof triggerDiagnose === 'function') { triggerDiagnose(); return 'triggerDiagnose()'; }
                return 'no-helper';
            }"""
        )
        page.wait_for_timeout(2000)
        results.append(f"진단 트리거: {triggered}")
        page.screenshot(path=str(out / "03-dashboard.png"), full_page=True)

        # 각 사이드바 뷰를 클릭하며 스크린샷 + 콘솔 에러 수집
        views = [
            ("dashboard", "오늘의 처방"),
            ("roadmap", "학습 로드맵"),
            ("problem", "문제 훈련"),
            ("tutorials", "과목 튜토리얼"),
            ("terms", "용어 사전"),
        ]
        for vid, label in views:
            nav = page.locator(f'[data-view="{vid}"]')
            if nav.count():
                nav.first.click()
                page.wait_for_timeout(1200)
                page.screenshot(path=str(out / f"10-{vid}.png"), full_page=True)
                results.append(f"뷰 '{label}' 전환 OK")
            else:
                results.append(f"뷰 '{label}' nav 없음")

        # 학습 로드맵의 학습경로 로드 버튼
        roadmap_nav = page.locator('[data-view="roadmap"]')
        if roadmap_nav.count():
            roadmap_nav.first.click()
            page.wait_for_timeout(600)
            lp = page.locator("#loadLearningPath")
            if lp.count() and lp.is_visible():
                lp.click()
                page.wait_for_timeout(1500)
                page.screenshot(path=str(out / "11-learning-path.png"), full_page=True)
                results.append("학습경로 버튼 클릭 OK")

        browser.close()

    print("=== 결과 ===")
    for r in results:
        print(" ", r)
    print(f"=== pageerror {len(page_errors)} ===")
    for e in page_errors:
        print("  PAGEERROR:", e)
    print(f"=== console error/warn {len(console_errors)} ===")
    for e in console_errors[:30]:
        print(" ", e)
    print(f"스크린샷: {out}")
    # pageerror(런타임 throw)가 있으면 실패 코드
    return 1 if page_errors else 0


if __name__ == "__main__":
    sys.exit(main())
