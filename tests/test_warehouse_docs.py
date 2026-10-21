"""데이터 사전 자동 생성 테스트 (DB 없이, 작은 가짜 dbt manifest로).

dbt manifest에서 열쇠(PK) · 연결(FK) · 계보를 제대로 읽는지, 문서에 그 결과가 들어가는지 확인합니다.
"""

from future_stress.warehouse_docs import (
    MULTI_TABLE,
    build_document,
    keys_and_links,
    relations_from_manifest,
    resolve_through_ephemeral,
    test_counts as count_tests,   # pytest가 test_로 시작하는 이름을 테스트로 착각하지 않게 다른 이름으로
)


def model(name, schema, depends_on=(), materialized="table"):
    return {"resource_type": "model", "name": name, "alias": name, "schema": schema, "description": f"{name} 설명",
            "config": {"materialized": materialized}, "depends_on": {"nodes": list(depends_on)}}


def dbt_test_node(name, attached, depends_on, kwargs=None, column=None):
    node = {"resource_type": "test", "attached_node": attached, "column_name": column,
            "depends_on": {"nodes": list(depends_on)}}
    if name:
        node["test_metadata"] = {"name": name, "kwargs": kwargs or {}}
    return node


FAKE_MANIFEST = {
    "sources": {"source.p.raw.card": {"schema": "raw", "identifier": "card", "description": "원본"}},
    "nodes": {
        "seed.p.age_groups": {"resource_type": "seed", "name": "age_groups", "schema": "ref", "description": "",
                              "config": {}, "depends_on": {"macros": []}},          # seed에는 nodes가 없음
        "model.p.int_city": model("int_city", "gold", ["source.p.raw.card"], materialized="ephemeral"),
        "model.p.stress": model("gold_stress", "gold", ["model.p.int_city"]),
        "model.p.by_age": model("gold_by_age", "gold", ["model.p.stress"]),
        "test.p.unique_stress": dbt_test_node("unique_combination", "model.p.stress", ["model.p.stress"],
                                          {"columns": ["district", "industry_code"]}),
        "test.p.unique_age": dbt_test_node("unique", "seed.p.age_groups", ["seed.p.age_groups"], column="age_group"),
        "test.p.link_case": dbt_test_node("composite_relationships", "model.p.by_age", ["model.p.by_age", "model.p.stress"],
                                      {"columns": ["district", "industry_code"]}),
        "test.p.link_age": dbt_test_node("relationships", "model.p.by_age", ["seed.p.age_groups", "model.p.by_age"],
                                     {"field": "age_group"}, column="main_age_group"),
        "test.p.source_not_null": dbt_test_node("not_null", None, ["source.p.raw.card"], column="amt"),
        "test.p.reconcile": dbt_test_node(None, None, ["source.p.raw.card", "model.p.stress"]),
    },
}


def test_ephemeral_is_skipped_and_lineage_goes_through_it():
    relations = relations_from_manifest(FAKE_MANIFEST)
    assert "model.p.int_city" not in relations                      # 표로 저장되지 않음
    assert relations["seed.p.age_groups"]["depends_on"] == []
    # gold_stress는 ephemeral(int_city)을 거쳐 원본에서 만들어짐 → 계보는 원본으로 이어져야 함
    assert resolve_through_ephemeral(FAKE_MANIFEST, ["model.p.int_city"]) == ["source.p.raw.card"]


def test_keys_and_links_come_from_tests():
    keys, links = keys_and_links(FAKE_MANIFEST)
    assert keys["model.p.stress"] == ["district", "industry_code"]
    assert keys["seed.p.age_groups"] == ["age_group"]
    by_parent = {link["parent"]: link for link in links}
    assert by_parent["model.p.stress"]["columns"] == ["district", "industry_code"]
    # 자식 열 이름과 부모 열 이름이 다른 연결 (main_age_group → age_group)
    assert by_parent["seed.p.age_groups"]["columns"] == ["main_age_group"]
    assert by_parent["seed.p.age_groups"]["parent_columns"] == ["age_group"]


def test_tests_without_attached_node_are_counted():
    counts = count_tests(FAKE_MANIFEST)
    assert counts["source.p.raw.card"] == {"not_null": 1}            # 원본에 붙은 테스트
    assert counts[MULTI_TABLE] == {"직접 만든 SQL 테스트": 1}           # 여러 표를 보는 대사 테스트


def test_document_draws_lineage_and_erd():
    relations = relations_from_manifest(FAKE_MANIFEST)
    tables = {uid: {**relation, "rows": 10, "columns": [("district", "text", "시군구"),
                                                          ("industry_code", "integer", "업종 코드"),
                                                          ("main_age_group", "text", "핵심 연령대"),
                                                          ("age_group", "text", "연령대")]}
              for uid, relation in relations.items()}
    document = build_document(FAKE_MANIFEST, tables, "2026-10-21 00:00")
    assert "raw_card --> gold_stress" in document                     # ephemeral을 건너뛴 계보
    assert "gold_stress ||--o{ gold_by_age" in document               # 열쇠 전체로 연결 → 정확히 하나
    assert "ref_age_groups ||--o{ gold_by_age" in document            # 부모 열 이름(age_group)으로 비교
    assert "테스트 6개" in document
