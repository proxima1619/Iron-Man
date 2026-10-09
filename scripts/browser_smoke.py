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
        page.get_by_label("데모 인증 토큰").fill(access["operator_token"])
        for speed, verdict in ((60, "차단"), (80, "보류")):
            page.get_by_label("목표 펌프 속도 (%)").fill(str(speed))
            with page.expect_response(lambda response: response.url.endswith("/evaluate")
                                      and response.request.method == "POST") as submitted:
                page.get_by_role("button", name="새 요청 만들고 검토").click()
            assert submitted.value.status == 202
            expect(page.locator(".badge")).to_have_text(verdict, timeout=30000)
            expect(page.get_by_role("alert")).to_have_count(0)
            expect(page.get_by_role("button", name="승인", exact=True)).to_be_disabled()
        page.get_by_role("button", name="저장된 요청 불러오기").click()
        expect(page.locator("ul button").first).to_be_visible()
        context.close()
        browser.close()
    print("PASS: Chromium Basic login, role header, request, automatic result polling, saved records")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access-file", type=Path, default=Path(".deploy-private/access.json"))
    parser.add_argument("--url")
    args = parser.parse_args()
    access = json.loads(args.access_file.read_text())
    run(access, args.url or access["url"])
