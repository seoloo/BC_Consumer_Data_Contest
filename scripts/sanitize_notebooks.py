from __future__ import annotations

import json
import re
import sys
from pathlib import Path


CLIENT_ID = re.compile(r"(?m)^(\s*client_id\s*=\s*)[\"'][^\"']*[\"']")
CLIENT_SECRET = re.compile(r"(?m)^(\s*client_secret\s*=\s*)[\"'][^\"']*[\"']")
WINDOWS_USER_PATH = re.compile(r"(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\"']+")


def sanitize_source(source: str) -> str:
    changed = False
    if CLIENT_ID.search(source):
        source = CLIENT_ID.sub(r'\1os.getenv("NAVER_CLIENT_ID")', source)
        changed = True
    if CLIENT_SECRET.search(source):
        source = CLIENT_SECRET.sub(r'\1os.getenv("NAVER_CLIENT_SECRET")', source)
        changed = True
    source = WINDOWS_USER_PATH.sub(".", source)
    if changed and not re.search(r"(?m)^\s*import\s+os\b", source):
        source = "import os\n" + source
    return source


def sanitize_notebook(source_path: Path, destination_path: Path) -> None:
    notebook = json.loads(source_path.read_text(encoding="utf-8"))
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        source = sanitize_source(source)
        cell["source"] = source.splitlines(keepends=True)
        cell["outputs"] = []
        cell["execution_count"] = None
    destination_path.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    source_dir = Path(sys.argv[1])
    destination_dir = Path(sys.argv[2])
    destination_dir.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(source_dir.glob("*.ipynb")):
        sanitize_notebook(source_path, destination_dir / source_path.name)


if __name__ == "__main__":
    main()
