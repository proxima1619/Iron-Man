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
        page.goto(url)
        expect(page.get_by_role("heading", name="설비 변경 요청 안전 관문")).to_be_visible()
        page.get_by_label("데모 인증 토큰").fill(access["approver_token"])
        expect(page.get_by_role("button", name="가상 설비 초기화")).to_be_enabled()
        page.get_by_role("button", name="가상 설비 초기화").click()
        page.get_by_label("데모 인증 토큰").fill(access["operator_token"])
        for speed, verdict in ((60, "차단"), (80, "승인 대기")):
            page.get_by_label("목표 펌프 속도 (%)").fill(str(speed))
            with page.expect_response(lambda response: response.url.endswith("/evaluate")
                                      and response.request.method == "POST") as submitted:
                page.get_by_role("button", name="새 요청 만들고 검토").click()
            assert submitted.value.status == 202
            expect(page.locator(".badge")).to_have_text(verdict, timeout=30000)
            expect(page.get_by_role("alert")).to_have_count(0)
            if speed == 60:
                expect(page.get_by_role("button", name="승인", exact=True)).to_be_disabled()
        page.get_by_label("데모 인증 토큰").fill(access["approver_token"])
        page.get_by_role("button", name="승인", exact=True).click()
        expect(page.locator(".badge")).to_have_text("승인 완료")
        with page.expect_response(lambda response: response.url.endswith("/execute")) as applied:
            page.get_by_role("button", name="가상 설비에 적용").click()
        receipt = applied.value.json()
        assert receipt["execution"]["virtual"] is True
        assert receipt["execution"]["state"]["target_pump_speed_pct"] == 80
        expect(page.locator(".badge")).to_have_text("가상 적용 완료")
        with page.expect_response("**/api/demo/advance") as advanced:
            page.get_by_role("button", name="가상 시간 10초 진행").click()
        assert 80 < advanced.value.json()["pump_speed_pct"] < 100
        # A new approved report cannot be applied after virtual time changes.
        page.get_by_role("button", name="가상 설비 초기화").click()
        page.get_by_role("button", name="새 요청 만들고 검토").click()
        expect(page.locator(".badge")).to_have_text("승인 대기", timeout=30000)
        page.get_by_role("button", name="승인", exact=True).click()
        expect(page.locator(".badge")).to_have_text("승인 완료")
        page.get_by_role("button", name="가상 시간 10초 진행").click()
        with page.expect_response(lambda response: response.url.endswith("/execute")) as denied:
            page.get_by_role("button", name="가상 설비에 적용").click()
        assert denied.value.status == 409
        expect(page.locator(".badge")).to_have_text("재검증 필요")
        page.get_by_role("button", name="저장된 요청 불러오기").click()
        expect(page.locator("ul button").first).to_be_visible()
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
