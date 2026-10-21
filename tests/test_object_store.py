"""객체 저장소(Bronze 보관) 테스트.

대부분은 메모리에만 저장하는 가짜 S3 클라이언트(FakeS3Client)로 확인합니다. Docker가 없어도 돌아가야 하기 때문입니다.
실제 SeaweedFS와 맞는지는 맨 아래 integration 테스트가 확인합니다 (컨테이너가 떠 있을 때만 돌고, 없으면 건너뜀).
"""

import io

import pytest
from botocore.exceptions import ClientError

from future_stress.medallion import DataQualityError, build_bronze
from future_stress.object_store import (
    MANIFEST_NAME,
    ObjectStore,
    batch_prefix,
    download_bronze,
    init_env,
    upload_bronze,
)
from future_stress.pipeline import run_pipeline


def not_found(operation):
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, operation)


class FakeS3Client:
    """boto3 S3 클라이언트에서 이 프로젝트가 쓰는 메서드만 흉내 냅니다. 객체는 {(버킷, 키): (내용, 메타데이터)}."""

    def __init__(self):
        self.buckets, self.objects, self.put_count = set(), {}, 0

    def head_bucket(self, Bucket):
        if Bucket not in self.buckets:
            raise not_found("HeadBucket")

    def create_bucket(self, Bucket):
        self.buckets.add(Bucket)

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise not_found("HeadObject")
        return {"Metadata": dict(self.objects[(Bucket, Key)][1])}

    def put_object(self, Bucket, Key, Body, Metadata):
        self.objects[(Bucket, Key)] = (bytes(Body), dict(Metadata))
        self.put_count += 1

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)][0])}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(key for bucket, key in self.objects if bucket == Bucket and key.startswith(Prefix))
        return {"Contents": [{"Key": key} for key in keys], "IsTruncated": False}


@pytest.fixture
def bronze_dir(synthetic_raw_dir, tmp_path):
    folder = tmp_path / "bronze"
    build_bronze(synthetic_raw_dir, folder)
    return folder


def test_upload_twice_skips_unchanged_files(bronze_dir):
    """두 번째 올릴 때 데이터 파일은 모두 '변경 없음'이고 실제로 다시 올리지 않아야 합니다 (멱등)."""
    store = ObjectStore(FakeS3Client())
    first = upload_bronze(bronze_dir, store, 202606)
    puts_after_first = store.client.put_count

    second = upload_bronze(bronze_dir, store, 202606)
    data_files = second[~second["파일"].str.endswith(MANIFEST_NAME)]
    assert set(first["상태"]) == {"신규"}
    assert set(data_files["상태"]) == {"변경 없음"}
    assert store.client.put_count == puts_after_first        # 영수증도 내용이 같으면 다시 안 올림
    assert all(key.startswith("batch_month=202606/") for key in first["파일"])


def test_download_restores_same_files(bronze_dir, tmp_path):
    store = ObjectStore(FakeS3Client())
    upload_bronze(bronze_dir, store, 202606)
    target, file_count = download_bronze(store, tmp_path / "cache", 202606)
    originals = sorted(p.relative_to(bronze_dir) for p in bronze_dir.rglob("*") if p.is_file())
    restored = sorted(p.relative_to(target) for p in target.rglob("*") if p.is_file())
    assert restored == originals and file_count == len(originals) - 1      # 영수증 1개 제외
    card = "card_spending/bc_card_202601_202606.csv"
    assert (target / card).read_bytes() == (bronze_dir / card).read_bytes()


def test_download_stops_when_object_was_changed(bronze_dir, tmp_path):
    """누가 버킷의 파일만 바꿔 두면 지문이 영수증과 달라 멈춰야 합니다."""
    store = ObjectStore(FakeS3Client())
    upload_bronze(bronze_dir, store, 202606)
    key = batch_prefix(202606) + "card_spending/bc_card_202601_202606.csv"
    store.client.objects[("bronze", key)] = (b"tampered", {})
    with pytest.raises(DataQualityError, match="bc_card_202601_202606.csv"):
        download_bronze(store, tmp_path / "cache", 202606)


def test_pipeline_reads_silver_input_from_object_store(synthetic_raw_dir, tmp_path):
    store = ObjectStore(FakeS3Client())
    tables = run_pipeline(synthetic_raw_dir, tmp_path / "output", tmp_path / "data", object_store=store)
    report = tables["quality_report"].set_index("검사")
    assert report.loc["객체 저장소 왕복 지문", "결과"] == "통과"
    assert "실패" not in set(report["결과"])
    assert (tmp_path / "data" / "bronze_cache" / MANIFEST_NAME).exists()


def test_init_env_writes_keys_once(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("KOSIS_API_KEY=", encoding="utf-8")          # 끝에 줄바꿈이 없는 기존 파일
    assert init_env(env_file) == ["S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_PORT",
                                  "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_PORT"]
    assert init_env(env_file) == []                                  # 두 번째는 아무것도 안 씀
    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "KOSIS_API_KEY=" and sum(line.startswith("S3_ACCESS_KEY=") for line in lines) == 1


@pytest.mark.integration
def test_real_seaweedfs_round_trip(tmp_path):
    """실제 SeaweedFS(docker compose up -d)에 작은 파일을 올리고 받아 봅니다. 저장소가 없으면 건너뜁니다."""
    try:
        store = ObjectStore.from_environment(bucket="bronze-test")
        store.ensure_bucket()
    except Exception as error:  # noqa: BLE001  (키 없음 · 연결 안 됨 모두 '건너뜀'으로)
        pytest.skip(f"객체 저장소에 연결할 수 없음: {type(error).__name__}")
    path = tmp_path / "hello.txt"
    path.write_text("안녕하세요", encoding="utf-8")
    first = store.upload_if_changed(path, "round-trip/hello.txt")
    assert store.upload_if_changed(path, "round-trip/hello.txt") == "변경 없음"
    assert first in {"신규", "변경 없음"}
    assert store.read_bytes("round-trip/hello.txt").decode("utf-8") == "안녕하세요"
