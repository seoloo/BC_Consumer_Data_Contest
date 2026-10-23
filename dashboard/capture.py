"""대시보드 화면을 PNG로 찍습니다 (README용). 원본 숫자가 드러나지 않게 항상 합성 데이터로 찍습니다.

사용법 (저장소 루트에서, 대시보드가 떠 있는 상태)
    .venv\\Scripts\\pip install playwright        # 한 번만. 브라우저는 이 PC의 Chrome을 씀 (따로 받지 않음)
    .venv\\Scripts\\python dashboard\\capture.py

왜 흐름도처럼 Chrome 명령 한 줄(--screenshot)로 찍지 않나요?
    Streamlit 화면은 페이지가 열린 뒤 웹소켓으로 데이터를 받아 그립니다. Chrome 명령 한 줄은 그걸 기다리지 않고
    빈 화면을 찍어서, 그림이 다 그려질 때까지 기다릴 수 있는 Playwright를 씁니다.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:38501/?data=synthetic&tab={tab}"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "dashboard"
TABS = ["overview", "ranking", "types", "detail"]


def capture(tabs=TABS):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1400, "height": 1150}, device_scale_factor=1.5,
                                color_scheme="light")
        for tab in tabs:
            page.goto(URL.format(tab=tab))
            # 앱이 다 돌면 Streamlit이 'running' 표시를 지웁니다. 그래프(vega)는 그 뒤에 그려지므로 조금 더 기다림.
            page.wait_for_selector("[data-testid='stApp'][data-test-script-state='notRunning']", timeout=60_000)
            page.wait_for_timeout(1_500)
            path = OUTPUT_DIR / f"{TABS.index(tab) + 1:02d}_{tab}.png"
            page.screenshot(path=path, full_page=True)
            print(f"{path.relative_to(OUTPUT_DIR.parents[1])}")
        browser.close()


if __name__ == "__main__":
    capture(sys.argv[1:] or TABS)
