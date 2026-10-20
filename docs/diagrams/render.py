"""흐름도 HTML을 PNG로 한 번에 변환합니다.

사용법 (저장소 루트에서)
    .venv\\Scripts\\python docs\\diagrams\\render.py            # 모든 흐름도
    .venv\\Scripts\\python docs\\diagrams\\render.py 08_roadmap  # 하나만

동작 방식
    설치된 Chrome(없으면 Edge)을 화면 없이(headless) 실행해 HTML을 캡처합니다.
    각 HTML 맨 위의 <!-- size: 1600x1800 --> 주석은 '최대' 캡처 크기입니다.
    캡처한 뒤 아래쪽에 남는 빈 배경을 자동으로 잘라내므로, 높이는 넉넉하게 적으면 됩니다.
    프로젝트가 진행되면 HTML 내용만 고치고 이 스크립트를 다시 실행하면 됩니다.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib.image as mpimg
import numpy as np

DIAGRAM_DIR = Path(__file__).resolve().parent
SCALE = 1.5             # 1600px 폭을 2400px로 저장 (README에서 확대해도 선명하게)
BOTTOM_MARGIN_PX = 56   # 잘라낸 뒤 내용 아래에 남길 여백 (CSS 기준 px)
BROWSER_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


def find_browser():
    for path in BROWSER_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("Chrome 또는 Edge를 찾지 못했습니다. BROWSER_CANDIDATES에 경로를 추가해 주세요.")


def read_size(html_path):
    """HTML 맨 위 <!-- size: 1600x1800 --> 주석에서 캡처 크기를 읽습니다."""
    match = re.search(r"<!--\s*size:\s*(\d+)x(\d+)\s*-->", html_path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"{html_path.name}에 <!-- size: 1600x1800 --> 주석이 없습니다.")
    return int(match.group(1)), int(match.group(2))


def render(html_path, browser):
    width, height = read_size(html_path)
    png_path = html_path.with_suffix(".png")
    with tempfile.TemporaryDirectory() as profile_dir:   # 매번 깨끗한 브라우저 프로필 사용
        subprocess.run(
            [
                str(browser), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                f"--user-data-dir={profile_dir}", f"--force-device-scale-factor={SCALE}",
                f"--window-size={width},{height}", f"--screenshot={png_path}", html_path.as_uri(),
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
        )
    trimmed_height = trim_bottom_background(png_path)
    print(f"{png_path.name}  ({width}x{round(trimmed_height / SCALE)}, 최대 {height})")


def trim_bottom_background(png_path):
    """이미지 아래쪽의 빈 배경을 잘라내고, 남은 높이(px)를 돌려줍니다.

    맨 아래 줄의 색을 배경색으로 보고, 아래에서부터 배경색이 아닌 첫 줄을 찾습니다.
    내용이 최대 높이를 넘으면(잘림) 경고를 출력합니다.
    """
    image = mpimg.imread(png_path)
    background = image[-1, 0]
    is_content_row = np.any(np.abs(image - background) > 0.01, axis=(1, 2))
    last_content_row = int(np.nonzero(is_content_row)[0].max())
    if last_content_row >= image.shape[0] - 2:
        print(f"  ! {png_path.name}: 내용이 최대 높이를 넘었습니다. size 주석의 높이를 늘려 주세요.")
        return image.shape[0]
    new_height = min(image.shape[0], last_content_row + 1 + int(BOTTOM_MARGIN_PX * SCALE))
    mpimg.imsave(png_path, image[:new_height])
    return new_height


def main():
    names = sys.argv[1:]
    html_files = sorted(p for p in DIAGRAM_DIR.glob("*.html") if not p.name.startswith("_"))
    if names:
        html_files = [p for p in html_files if p.stem in names]
    browser = find_browser()
    for html_path in html_files:
        render(html_path, browser)


if __name__ == "__main__":
    main()
