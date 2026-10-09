"""Optional Chromium smoke test. CI installs Playwright and trusts its local CA.

Uses public browser access and real fetch, without mocked APIs,
screenshots, traces, credential logging or TLS verification bypass.
"""
import argparse
import json
import re
from pathlib import Path


def run(access, url):
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        expect(page.get_by_role("heading", name=re.compile("설비를 바꾸기 전에"))).to_be_visible()
        expect(page.get_by_role("link", name="TEP 검토 콘솔 ↗")).to_have_attribute("href", "#review")
        page.goto(url + "/#review")
        expect(page.get_by_role("heading", name="변경 전에, 결과를 확인합니다.")).to_be_visible()
        page.get_by_label("데모 토큰").fill(access["approver_token"])
        page.get_by_role("button", name="연결 확인").click()
        # Default workflow is now TEP. Keep the legacy virtual-plant regression explicit.
        page.get_by_role("combobox", name=re.compile(r"^모델")).select_option("cooling")
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
        page.get_by_role("combobox", name=re.compile(r"^모델")).select_option("tep")
        for variable in ("XMV10", "XMV11"):
            page.get_by_role("combobox", name=re.compile(r"^냉각수 입력")).select_option(variable)
            page.get_by_label("예측 구간 (초)").fill("600")
            page.get_by_role("button", name="요청 생성 · 시뮬레이션 검토").click()
            expect(page.locator(".review > section:first-child .badge")).to_have_text("보류", timeout=30000)
            expect(page.get_by_role("heading", name="TEP 외부 시뮬레이션 비교")).to_be_visible()
            expect(page.get_by_role("heading", name="TEP 근거·역근거 검토")).to_be_visible()
            expect(page.get_by_text("실행 상태: completed", exact=True)).to_be_visible()
            expect(page.get_by_role("img", name="XMEAS9 기준 및 변경 시계열, degC")).to_be_visible()
            expect(page.get_by_role("button", name="가상 명령 승인", exact=True)).to_be_disabled()
            expect(page.get_by_role("button", name="승인한 가상 명령 적용")).to_be_disabled()
        # Cooling-only experience must not interpret TEP profiles as sensor snapshots.
        page.goto(url + "/#demo")
        expect(page.get_by_role("heading", name="저장된 결과를 읽고, AI 설명을 받아보세요.")).to_be_visible()
        page.get_by_text("데모 연결 설정", exact=True).click()
        page.get_by_label("요청 담당자 토큰").fill(access["operator_token"])
        page.get_by_role("button", name="저장된 기록 보기").click()
        records = page.get_by_label("검토할 저장 데이터")
        expect(records).to_be_visible()
        options = records.locator("option").all_text_contents()[1:]
        assert options and all("% ·" in option and "undefined" not in option for option in options)
        records.select_option(index=1)
        expect(page.get_by_role("heading", name="저장된 결과로 보는 판단 근거")).to_be_visible()
        assert not errors, f"Browser runtime errors: {len(errors)}"
        context.close()
        browser.close()
    print("PASS: Chromium login, cooling approval, stale approval denial, real TEP XMV10/XMV11 charts and disabled approval")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access-file", type=Path, default=Path(".deploy-private/access.json"))
    parser.add_argument("--url")
    args = parser.parse_args()
    access = json.loads(args.access_file.read_text())
    run(access, args.url or access["url"])
