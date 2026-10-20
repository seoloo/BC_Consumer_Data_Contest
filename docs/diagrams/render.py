"""흐름도 HTML을 PNG로 한 번에 변환합니다.

사용법 (저장소 루트에서)
    .venv\\Scripts\\python docs\\diagrams\\render.py            # 모든 흐름도
    .venv\\Scripts\\python docs\\diagrams\\render.py 09_roadmap  # 하나만

만들어지는 파일
    docs/diagrams/<이름>.png          전체 한 장 (보관 · 전체 보기용)
    docs/diagrams/parts/<이름>_<n>.png 주제별로 나눈 조각 (README · 블로그 게시용)

동작 방식
    설치된 Chrome(없으면 Edge)을 화면 없이(headless) 실행해 HTML을 캡처합니다.
    각 HTML 맨 위의 <!-- size: 1600x1800 --> 주석은 '최대' 캡처 크기입니다.
    캡처한 뒤 아래쪽에 남는 빈 배경을 자동으로 잘라내므로, 높이는 넉넉하게 적으면 됩니다.

나누는 방법
    HTML 안의 블록에 data-part="1" 처럼 조각 번호를 붙여 둡니다 (여러 조각에 걸치면 "2 3").
    조각 n을 만들 때는 번호가 n이 아닌 블록을 숨기고 캡처합니다. 제목(header)과 아래 목록(footer)은
    모든 조각에 남기고, 제목 옆에 'n / 전체' 표시를 붙여 한 장만 봐도 어떤 그림의 몇 번째인지 알 수 있게 합니다.
    그림이 길어서 안 보인다면 HTML의 data-part 번호만 바꾸면 됩니다.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib.image as mpimg
import numpy as np

DIAGRAM_DIR = Path(__file__).resolve().parent
PARTS_DIR = DIAGRAM_DIR / "parts"
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


def read_size(html_text, name):
    """HTML 맨 위 <!-- size: 1600x1800 --> 주석에서 캡처 크기를 읽습니다."""
    match = re.search(r"<!--\s*size:\s*(\d+)x(\d+)\s*-->", html_text)
    if not match:
        raise ValueError(f"{name}에 <!-- size: 1600x1800 --> 주석이 없습니다.")
    return int(match.group(1)), int(match.group(2))


def find_part_numbers(html_text):
    """HTML에 붙은 data-part 번호를 모두 모읍니다. 예: data-part="2 3" → {2, 3}"""
    numbers = set()
    for value in re.findall(r'data-part="([^"]+)"', html_text):
        numbers.update(int(number) for number in value.split())
    return sorted(numbers)


def capture(html_path, png_path, width, height, browser):
    """HTML 한 개를 PNG로 캡처하고 아래쪽 빈 배경을 잘라냅니다. 남은 높이(CSS px)를 돌려줍니다."""
    with tempfile.TemporaryDirectory() as profile_dir:   # 매번 깨끗한 브라우저 프로필 사용
        subprocess.run(
            [
                str(browser), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                f"--user-data-dir={profile_dir}", f"--force-device-scale-factor={SCALE}",
                f"--window-size={width},{height}", f"--screenshot={png_path}", html_path.as_uri(),
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
        )
    return round(trim_bottom_background(png_path) / SCALE)


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


def make_part_html(html_text, part, total):
    """조각 하나만 보이도록 숨김 규칙과 'n / 전체' 표시를 넣은 HTML을 만듭니다."""
    hide_rule = f'<style>[data-part]:not([data-part~="{part}"]) {{ display: none !important; }}</style>'
    html_text = html_text.replace("</head>", hide_rule + "\n</head>", 1)
    return re.sub(
        r'(<div class="eyebrow">.*?)</div>',
        rf'\1<span class="part-no">{part} / {total}</span></div>',
        html_text, count=1, flags=re.S,
    )


def render(html_path, browser):
    html_text = html_path.read_text(encoding="utf-8")
    width, height = read_size(html_text, html_path.name)

    full_height = capture(html_path, html_path.with_suffix(".png"), width, height, browser)
    print(f"{html_path.stem}.png  ({width}x{full_height})")

    parts = find_part_numbers(html_text)
    if not parts:
        return
    PARTS_DIR.mkdir(exist_ok=True)
    for part in parts:
        # 임시 HTML은 _style.css를 찾을 수 있게 같은 폴더에 만들고, 캡처 후 지웁니다.
        temp_html = DIAGRAM_DIR / f"_part_{html_path.stem}_{part}.html"
        temp_html.write_text(make_part_html(html_text, part, len(parts)), encoding="utf-8")
        try:
            png_path = PARTS_DIR / f"{html_path.stem}_{part}.png"
            part_height = capture(temp_html, png_path, width, height, browser)
            print(f"  parts/{png_path.name}  ({width}x{part_height})")
        finally:
            temp_html.unlink(missing_ok=True)


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
