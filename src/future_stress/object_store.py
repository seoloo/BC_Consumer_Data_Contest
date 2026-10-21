"""Bronze 원본을 S3 호환 객체 저장소(SeaweedFS)에 올리고 내려받습니다.

왜 필요한가요?
    지금까지 Bronze는 이 PC의 data/bronze 폴더였습니다. 이 PC 밖에서는 보이지 않고,
    나중에 Airflow · dbt 같은 다른 서비스가 같은 원본을 함께 쓰기 어렵습니다.
    실무의 데이터 레이크처럼 원본을 객체 저장소(버킷)에 두고, 각 단계가 거기서 읽게 합니다.

왜 SeaweedFS인가요? (2026-10-21 결정, 사용자 "seaweedFS로 진행하되 …")
    처음 계획은 MinIO였지만, MinIO는 2025-10 무료판 이미지 배포를 멈췄고 2026-09 Docker Hub에서 이미지가 지워졌습니다.
    SeaweedFS는 같은 S3 API를 지원하고, 이 PC의 다른 프로젝트에서 이미 같은 버전(4.48)을 쓰고 있습니다.
    코드는 S3 표준 라이브러리(boto3)로만 짜서, 저장소를 바꾸거나 AWS S3로 옮겨도 접속 주소와 키만 바꾸면 됩니다.

버킷 안 구조 (배치 월마다 폴더)
    bronze/
      batch_month=202606/
        _manifest.json                            Bronze 적재 영수증 (파일마다 SHA-256)
        card_spending/bc_card_202601_202606.csv
        future_population/...
    'batch_month=' 형식은 데이터 레이크에서 흔히 쓰는 파티션 이름입니다. 한 달 데이터에 문제가 생기면
    그 폴더만 다시 올리고 그 달만 다시 처리하면 됩니다.

지키는 것
    1. 같은 파일은 다시 올리지 않습니다. 올릴 때 객체 메타데이터에 SHA-256을 적어 두고, 다음에 비교합니다 (멱등).
    2. 내려받은 파일의 지문을 영수증과 다시 맞춰 봅니다. 하나라도 다르면 DataQualityError로 멈춥니다.
    3. 계정 키는 코드에 쓰지 않고 .env에서만 읽습니다. local_env가 이 PC 전용 키를 만들어 줍니다.

실행 방법 (저장소 루트에서)
    .venv\\Scripts\\python -m future_stress.local_env               # .env에 로컬 서비스 계정 만들기 (처음 한 번)
    docker compose up -d                                             # 저장소 띄우기
    .venv\\Scripts\\python -m future_stress.object_store status        # 버킷에 무엇이 있는지 보기
    .venv\\Scripts\\python -m future_stress.pipeline --object-store    # Bronze를 저장소에 올리고, 거기서 받아 Silver부터 실행
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

import boto3
import pandas as pd
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError

from . import config
from .io_utils import read_env_value
from .local_env import DEFAULT_S3_PORT, init_env  # noqa: F401  (init_env: 예전 명령 'object_store init-env' 유지용)
from .medallion import DataQualityError

DEFAULT_BUCKET = "bronze"
SYNTHETIC_BUCKET = "bronze-synthetic"    # 합성 데이터용. 원본과 파일 이름이 같아 같은 버킷에 두면 덮어쓰기 때문
MANIFEST_NAME = "_manifest.json"
FINGERPRINT_METADATA_KEY = "sha256"    # 객체 메타데이터 이름 (S3에서는 x-amz-meta-sha256으로 저장됨)


def batch_prefix(batch_month):
    """배치 월 폴더 이름. 예: 202606 → 'batch_month=202606/'"""
    return f"batch_month={batch_month}/"


def is_not_found(error):
    """S3 오류가 '없음(404)'인지. 없음은 정상적인 상황(처음 올림)이라 오류와 구분해야 합니다."""
    return error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}


class ObjectStore:
    """버킷 하나를 다루는 얇은 창구.

    boto3 클라이언트를 밖에서 받습니다(의존성 주입). 실제로는 SeaweedFS에 연결된 클라이언트를,
    테스트에서는 메모리에만 저장하는 가짜 클라이언트를 넣어 Docker 없이도 확인할 수 있게 하기 위해서입니다.
    """

    def __init__(self, client, bucket=DEFAULT_BUCKET):
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_environment(cls, env_file=None, bucket=DEFAULT_BUCKET):
        """.env의 S3_ACCESS_KEY · S3_SECRET_KEY · S3_PORT로 로컬 SeaweedFS에 연결합니다."""
        try:
            port = read_env_value("S3_PORT", env_file)
        except ValueError:
            port = DEFAULT_S3_PORT
        # 이 PC에서는 127.0.0.1:59100, 컨테이너 안(Airflow)에서는 서비스 이름(http://object-store:8333)으로 접속합니다.
        # 그래서 S3_ENDPOINT_URL이 있으면 그 주소를 쓰고, 없으면 이 PC 주소를 씁니다.
        endpoint_url = os.getenv("S3_ENDPOINT_URL") or f"http://127.0.0.1:{port}"
        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=read_env_value("S3_ACCESS_KEY", env_file),
            aws_secret_access_key=read_env_value("S3_SECRET_KEY", env_file),
            region_name="us-east-1",          # S3 API가 지역 이름을 요구해서 넣는 값 (로컬이라 의미 없음)
            config=Config(
                # 'http://주소/버킷/키' 형식. 로컬 저장소는 '버킷.주소' 형식의 도메인이 없기 때문입니다.
                s3={"addressing_style": "path"},
                # 연결 끊김 같은 일시적 오류는 boto3가 알아서 다시 시도합니다 (09 API 수집 · 재시도 참고).
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5, read_timeout=60,
            ),
        )
        return cls(client, bucket)

    def ensure_bucket(self):
        """버킷이 없으면 만듭니다. 이미 있으면 아무것도 하지 않습니다 (몇 번 불러도 같음)."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as error:
            if not is_not_found(error):
                raise
            self.client.create_bucket(Bucket=self.bucket)

    def remote_fingerprint(self, key):
        """저장소에 있는 객체의 SHA-256 (올릴 때 메타데이터에 적어 둔 값). 객체가 없으면 None."""
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if is_not_found(error):
                return None
            raise
        return response.get("Metadata", {}).get(FINGERPRINT_METADATA_KEY)

    def upload_if_changed(self, local_path, key):
        """내용이 다를 때만 올립니다. Returns: '신규' / '변경' / '변경 없음'"""
        content = Path(local_path).read_bytes()
        fingerprint = hashlib.sha256(content).hexdigest()
        remote = self.remote_fingerprint(key)
        if remote == fingerprint:
            return "변경 없음"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content,
                               Metadata={FINGERPRINT_METADATA_KEY: fingerprint})
        return "신규" if remote is None else "변경"

    def read_bytes(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def list_keys(self, prefix=""):
        """prefix로 시작하는 객체 키를 모두 돌려줍니다. 한 번에 1,000개까지만 오므로 이어 받기를 반복합니다."""
        keys, token = [], None
        while True:
            options = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                options["ContinuationToken"] = token
            response = self.client.list_objects_v2(**options)
            keys += [item["Key"] for item in response.get("Contents", [])]
            if not response.get("IsTruncated"):
                return sorted(keys)
            token = response["NextContinuationToken"]


# ===========================================================================
# Bronze 올리기 · 내려받기
# ===========================================================================

def upload_bronze(bronze_dir, store, batch_month=None):
    """로컬 Bronze(원본 + 영수증)를 버킷의 배치 월 폴더에 올립니다.

    영수증(_manifest.json)은 적재 시각이 들어 있어 실행할 때마다 '변경'이 됩니다. 데이터 파일은 같으면 '변경 없음'.

    Returns:
        파일 | 상태(신규/변경/변경 없음) | 크기
    """
    bronze_dir = Path(bronze_dir)
    batch_month = batch_month or config.LAST_MONTH
    manifest = json.loads((bronze_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    store.ensure_bucket()

    rows = []
    for entry in manifest["files"]:
        key = batch_prefix(batch_month) + entry["bronze_path"]
        rows.append({"파일": key, "상태": store.upload_if_changed(bronze_dir / entry["bronze_path"], key),
                     "크기": entry["bytes"]})
    manifest_key = batch_prefix(batch_month) + MANIFEST_NAME
    rows.append({"파일": manifest_key, "상태": store.upload_if_changed(bronze_dir / MANIFEST_NAME, manifest_key),
                 "크기": (bronze_dir / MANIFEST_NAME).stat().st_size})
    return pd.DataFrame(rows)


def download_bronze(store, target_dir, batch_month=None):
    """버킷의 배치 월 폴더를 내려받고, 파일마다 지문을 영수증과 맞춰 봅니다.

    왜 다시 맞춰 보나요?
        올리기 · 내려받기 중에 파일이 잘리거나, 누가 버킷의 파일만 바꿔 두었을 수 있습니다.
        영수증의 지문과 다르면 그 파일로 만든 Silver · Gold는 믿을 수 없으므로 멈춥니다.

    Returns:
        (내려받은 폴더, 확인한 파일 수)
    """
    target_dir = Path(target_dir)
    batch_month = batch_month or config.LAST_MONTH
    prefix = batch_prefix(batch_month)
    manifest_key = prefix + MANIFEST_NAME
    if manifest_key not in store.list_keys(prefix):
        raise FileNotFoundError(f"버킷 '{store.bucket}'에 {manifest_key}가 없습니다. 먼저 Bronze를 올려 주세요.")

    manifest_bytes = store.read_bytes(manifest_key)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    mismatched = []
    for entry in manifest["files"]:
        content = store.read_bytes(prefix + entry["bronze_path"])
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            mismatched.append(entry["bronze_path"])
            continue
        path = target_dir / entry["bronze_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    if mismatched:
        raise DataQualityError("객체 저장소에서 받은 파일의 지문이 영수증과 다릅니다: " + ", ".join(mismatched))
    (target_dir / MANIFEST_NAME).write_bytes(manifest_bytes)
    return target_dir, len(manifest["files"])


# ===========================================================================
# 처음 설정 · 상태 보기
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="Bronze 객체 저장소(SeaweedFS) 도구")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-env", help=".env에 로컬 서비스 계정 만들기 (python -m future_stress.local_env와 같음)")
    status = commands.add_parser("status", help="버킷에 있는 객체 보기")
    status.add_argument("--prefix", default="")
    upload = commands.add_parser("upload", help="data/bronze를 버킷에 올리기")
    upload.add_argument("--bronze-dir", default=config.BRONZE_DIR)
    upload.add_argument("--batch-month", type=int, default=config.LAST_MONTH)
    arguments = parser.parse_args()

    try:
        if arguments.command == "init-env":
            written = init_env()
            print("새로 쓴 값: " + ", ".join(written) if written else ".env에 이미 S3 계정 키가 있습니다.")
        elif arguments.command == "status":
            store = ObjectStore.from_environment()
            store.ensure_bucket()
            keys = store.list_keys(arguments.prefix)
            print(f"버킷 '{store.bucket}' 객체 {len(keys)}개")
            print("\n".join(keys))
        else:
            report = upload_bronze(arguments.bronze_dir, ObjectStore.from_environment(), arguments.batch_month)
            print(report.to_string(index=False))
    except ValueError as error:
        raise SystemExit(f"[중단] {error}")
    except EndpointConnectionError:
        # Docker를 켜지 않았거나 컨테이너가 아직 뜨지 않은 경우. 긴 traceback 대신 할 일을 알려 줍니다.
        raise SystemExit("[중단] 객체 저장소에 연결할 수 없습니다. 'docker compose up -d'로 띄운 뒤 다시 실행해 주세요.")


if __name__ == "__main__":
    main()
