"""Optional Chromium smoke test. CI installs Playwright and trusts its local CA.

Uses real browser Basic authentication and real fetch, without mocked APIs,
screenshots, traces, credential logging or TLS verification bypass.
"""
import argparse
import json
from pathlib import Path


def run(access, url):
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(http_credentials={
            "username": access["username"], "password": access["password"], "origin": url,
        })
        page = context.new_page()
        page.goto(url + "/#review")
        expect(page.get_by_role("heading", name="변경 전에, 결과를 확인합니다.")).to_be_visible()
        page.get_by_label("데모 토큰").fill(access["approver_token"])
        page.get_by_role("button", name="연결 확인").click()
        # Default workflow is now TEP. Keep the legacy virtual-plant regression explicit.
        page.get_by_label("모델", exact=True).select_option("cooling")
        expect(page.get_by_role("button", name="가상 설비 초기화")).to_be_enabled()
        page.get_by_role("button", name="가상 설비 초기화").click()
        page.get_by_label("데모 토큰").fill(access["operator_token"])
        page.get_by_role("button", name="연결 확인").click()
        for speed, verdict in ((60, "차단"), (80, "승인 대기")):
            if speed == 80:
                page.get_by_label("데모 토큰").fill(access["approver_token"])
                page.get_by_role("button", name="연결 확인").click()
                with page.expect_response("**/api/demo/state") as changed:
                    page.get_by_role("button", name="데모 부하 0.6으로 변경").click()
                assert changed.value.status == 200
                page.get_by_label("데모 토큰").fill(access["operator_token"])
                page.get_by_role("button", name="연결 확인").click()
            page.get_by_label("목표 속도 (%)").fill(str(speed))
            with page.expect_response(lambda response: response.url.endswith("/evaluate")
                                      and response.request.method == "POST") as submitted:
                page.get_by_role("button", name="요청 생성 · 시뮬레이션 검토").click()
            assert submitted.value.status == 202
            expect(page.locator(".review > section:first-child .badge")).to_have_text(verdict, timeout=30000)
            expect(page.get_by_role("alert")).to_have_count(0)
            if speed == 60:
                expect(page.get_by_role("button", name="가상 명령 승인", exact=True)).to_be_disabled()
        page.get_by_label("데모 토큰").fill(access["approver_token"])
        page.get_by_role("button", name="연결 확인").click()
        # Reconnecting refreshes report details and resets the confirmation box.
        # Wait for that operation before checking the human acknowledgement.
        expect(page.get_by_role("button", name="연결 확인")).to_be_enabled()
        page.get_by_label("판단 이유").fill("합성 시연 보고서와 모델 한계 확인")
        page.get_by_role("checkbox").check()
        page.get_by_role("button", name="가상 명령 승인", exact=True).click()
        expect(page.locator(".review > section:first-child .badge")).to_have_text("승인 완료")
        with page.expect_response(lambda response: response.url.endswith("/execute")) as applied:
            page.get_by_role("button", name="승인한 가상 명령 적용").click()
        receipt = applied.value.json()
        assert receipt["execution"]["virtual"] is True
        assert receipt["execution"]["state"]["target_pump_speed_pct"] == 80
        expect(page.locator(".review > section:first-child .badge")).to_have_text("가상 적용 완료")
        with page.expect_response("**/api/demo/advance") as advanced:
            page.get_by_role("button", name="가상 시간 10초 진행").click()
        assert 80 < advanced.value.json()["pump_speed_pct"] < 100
        # A new approved report cannot be applied after virtual time changes.
        page.get_by_role("button", name="가상 설비 초기화").click()
        with page.expect_response("**/api/demo/state") as changed:
            page.get_by_role("button", name="데모 부하 0.6으로 변경").click()
        assert changed.value.status == 200
        page.get_by_role("button", name="요청 생성 · 시뮬레이션 검토").click()
        expect(page.locator(".review > section:first-child .badge")).to_have_text("승인 대기", timeout=30000)
        page.get_by_role("checkbox").check()
        page.get_by_role("button", name="가상 명령 승인", exact=True).click()
        expect(page.locator(".review > section:first-child .badge")).to_have_text("승인 완료")
        page.get_by_role("button", name="가상 시간 10초 진행").click()
        with page.expect_response(lambda response: response.url.endswith("/execute")) as denied:
            page.get_by_role("button", name="승인한 가상 명령 적용").click()
        assert denied.value.status == 409
        expect(page.locator(".review > section:first-child .badge")).to_have_text("재검증 필요")
        page.get_by_role("button", name="새로고침", exact=True).click()
        expect(page.locator(".request-list button").first).to_be_visible()
        page.get_by_label("모델", exact=True).select_option("tep")
        page.get_by_label("예측 구간 (초)").fill("60")
        page.get_by_role("button", name="요청 생성 · 시뮬레이션 검토").click()
        expect(page.locator(".review > section:first-child .badge")).to_have_text("보류", timeout=30000)
        expect(page.get_by_role("heading", name="TEP 외부 시뮬레이션 비교")).to_be_visible()
        expect(page.get_by_text("실행 상태: completed", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="가상 명령 승인", exact=True)).to_be_disabled()
        context.close()
        browser.close()
    print("PASS: Chromium login, blocked request, human approval, virtual application, stale approval denial, records")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access-file", type=Path, default=Path(".deploy-private/access.json"))
    parser.add_argument("--url")
    args = parser.parse_args()
    access = json.loads(args.access_file.read_text())
    run(access, args.url or access["url"])
