"""로컬 서비스(객체 저장소 · PostgreSQL) 계정을 .env에 만들어 줍니다.

왜 필요한가요?
    docker-compose.yml의 서비스들은 계정 키 · 비밀번호를 .env에서 받습니다. 키를 compose 파일이나
    코드에 적으면 git에 올라가기 때문입니다. 이 PC 안(127.0.0.1)에서만 쓰는 값이라 무작위로 만들어도 됩니다.

실행 방법 (저장소 루트에서, 처음 한 번)
    .venv\\Scripts\\python -m future_stress.local_env

이미 있는 값은 건드리지 않고, 없는 값만 덧붙입니다. 값은 화면에 출력하지 않습니다.
"""

import secrets
from pathlib import Path

from . import config

DEFAULT_S3_PORT = "59100"          # 다른 프로젝트가 쓰는 59000번과 겹치지 않게
DEFAULT_POSTGRES_PORT = "55532"    # 다른 프로젝트가 쓰는 55432번과 겹치지 않게
DEFAULT_POSTGRES_DB = "future_stress"
DEFAULT_POSTGRES_USER = "future_stress"


def new_local_values():
    """새로 만들 값. 부를 때마다 키 · 비밀번호는 무작위로 새로 만듭니다."""
    return {
        "객체 저장소(SeaweedFS)": {
            "S3_ACCESS_KEY": secrets.token_hex(10),
            "S3_SECRET_KEY": secrets.token_urlsafe(30),
            "S3_PORT": DEFAULT_S3_PORT,
        },
        "데이터 웨어하우스(PostgreSQL)": {
            "POSTGRES_USER": DEFAULT_POSTGRES_USER,
            "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
            "POSTGRES_DB": DEFAULT_POSTGRES_DB,
            "POSTGRES_PORT": DEFAULT_POSTGRES_PORT,
        },
    }


def init_env(env_file=None):
    """.env에 없는 로컬 서비스 값만 덧붙입니다.

    Returns: 새로 쓴 이름 목록 (모두 있으면 빈 목록)
    """
    env_file = Path(env_file or config.PROJECT_ROOT / ".env")
    existing = env_file.read_text(encoding="utf-8-sig") if env_file.exists() else ""
    # 값이 들어 있는 이름만 '있음'으로 봅니다. 'KEY=' 처럼 비어 있으면 새로 만들어야 하기 때문입니다.
    present = {line.partition("=")[0].strip() for line in existing.splitlines() if line.partition("=")[2].strip()}

    blocks, written = [], []
    for service, values in new_local_values().items():
        missing = {name: value for name, value in values.items() if name not in present}
        if missing:
            blocks.append([f"# 로컬 {service} · 이 PC에서만 쓰는 값 (local_env.init_env가 만듦)"]
                          + [f"{name}={value}" for name, value in missing.items()])
            written += list(missing)
    if blocks:
        separator = ""
        if existing:
            # 기존 내용 끝에 줄바꿈이 없으면 붙여 쓰지 않도록 하나 넣고, 한 줄을 띄워 구분합니다.
            separator = ("" if existing.endswith("\n") else "\n") + "\n"
        with open(env_file, "a", encoding="utf-8") as file:
            file.write(separator + "\n\n".join("\n".join(block) for block in blocks) + "\n")
    return written


def main():
    written = init_env()
    print("새로 쓴 값: " + ", ".join(written) if written else ".env에 로컬 서비스 값이 모두 있습니다.")


if __name__ == "__main__":
    main()
