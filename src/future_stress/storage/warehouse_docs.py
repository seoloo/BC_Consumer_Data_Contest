"""데이터 웨어하우스 데이터 사전 · 계보 · ERD를 자동으로 만듭니다. (Phase 3-4)

왜 자동으로 만드나요?
    표 · 열 설명을 손으로 쓴 문서는 표가 바뀌면 곧 틀려집니다. 설명은 dbt schema.yml 한 곳에만 쓰고
    (dbt가 PostgreSQL COMMENT로도 저장), 이 스크립트가 실제 DB와 dbt 실행 결과(manifest.json)를 읽어
    문서를 다시 만듭니다. 그래서 문서와 실제 표가 어긋나지 않습니다.

무엇을 읽나요?
    PostgreSQL       표마다 열 · 타입 · 설명(COMMENT) · 행 수
    dbt manifest     표 사이 계보(어느 표가 어느 표로 만들어지나), 테스트(열쇠 · 연결)
                     - unique / unique_combination 테스트 → 열쇠(PK)
                     - relationships / composite_relationships 테스트 → 연결선(FK)
                     테스트가 곧 ERD의 근거라서, 그림에 있는 연결은 모두 매번 검사되는 연결입니다.

만드는 것
    docs/warehouse/README.md   데이터 사전 (GitHub에서 Mermaid 그림이 바로 보임)

실행 방법 (저장소 루트에서, docker compose up -d 와 dbt build 뒤)
    docker compose run --rm dbt build                     # manifest.json을 원본 기준(dev)으로 새로 만듦
    .venv\\Scripts\\python -m future_stress.storage.warehouse_docs
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import psycopg

from .. import config
from .warehouse import Warehouse

MANIFEST_PATH = config.PROJECT_ROOT / "dbt" / "target" / "manifest.json"
OUTPUT_PATH = config.PROJECT_ROOT / "docs" / "warehouse" / "README.md"
SCHEMA_ORDER = ["raw", "ref", "silver", "gold"]
SCHEMA_ROLES = {
    "raw": "원본 표기 그대로 (파이썬 warehouse.py가 넣음)",
    "ref": "코드 · 이름 기준표 (dbt seed)",
    "silver": "거르기 · 코드 → 이름 · 표준화 (dbt 모델)",
    "gold": "소비구조 · 프로필 · Future Stress · 4유형 (dbt 모델)",
}
KEY_TESTS = {"unique", "unique_combination"}
LINK_TESTS = {"relationships", "composite_relationships"}


# ===========================================================================
# dbt manifest 읽기 (DB 없이 테스트할 수 있게 순수 함수로)
# ===========================================================================

def read_manifest(path=MANIFEST_PATH):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path}가 없습니다. 먼저 'docker compose run --rm dbt build'를 실행해 주세요.")
    return json.loads(path.read_text(encoding="utf-8"))


def relations_from_manifest(manifest):
    """표로 저장되는 것(source · seed · 모델) 목록. ephemeral 모델은 표가 아니라 빠집니다.

    Returns: {dbt 고유 id: {'schema', 'name', 'kind', 'description', 'depends_on'}}
    """
    relations = {}
    for unique_id, source in manifest["sources"].items():
        relations[unique_id] = {"schema": source["schema"], "name": source["identifier"], "kind": "source",
                                "description": source.get("description", ""), "depends_on": []}
    for unique_id, node in manifest["nodes"].items():
        if node["resource_type"] == "seed":
            kind = "seed"
        elif node["resource_type"] == "model" and node["config"].get("materialized") != "ephemeral":
            kind = "model"
        else:
            continue
        relations[unique_id] = {"schema": node["schema"], "name": node.get("alias") or node["name"], "kind": kind,
                                "description": node.get("description", ""),
                                "depends_on": node["depends_on"].get("nodes", [])}
    return relations


def resolve_through_ephemeral(manifest, unique_ids):
    """ephemeral(표로 저장하지 않는 중간 단계)을 건너뛰고 실제 표까지 따라갑니다. 계보 그림에서 끊기지 않게."""
    resolved = []
    for unique_id in unique_ids:
        node = manifest["nodes"].get(unique_id)
        if node and node["resource_type"] == "model" and node["config"].get("materialized") == "ephemeral":
            resolved += resolve_through_ephemeral(manifest, node["depends_on"].get("nodes", []))
        else:
            resolved.append(unique_id)
    return resolved


def keys_and_links(manifest):
    """테스트에서 열쇠(PK)와 연결(FK)을 뽑습니다.

    Returns:
        keys:  {표 id: [열쇠 열, ...]}
        links: [{'child', 'parent', 'columns', 'parent_columns'}]  child의 columns 값이 parent의 parent_columns에 반드시 있음
    """
    keys, links = {}, []
    for node in manifest["nodes"].values():
        metadata = node.get("test_metadata") or {}
        name, kwargs = metadata.get("name"), metadata.get("kwargs", {})
        child = node.get("attached_node")
        if node["resource_type"] != "test" or not child:
            continue
        if name == "unique_combination":
            keys[child] = list(kwargs["columns"])
        elif name == "unique" and child not in keys:
            keys[child] = [node["column_name"]]
        elif name in LINK_TESTS:
            parents = [unique_id for unique_id in node["depends_on"].get("nodes", []) if unique_id != child]
            if name == "composite_relationships":
                columns = parent_columns = list(kwargs["columns"])
            else:
                # relationships: 자식 열 이름(column_name)과 부모 열 이름(field)이 다를 수 있음 (main_age_group → age_group)
                columns, parent_columns = [node["column_name"]], [kwargs["field"]]
            if parents:
                links.append({"child": child, "parent": parents[0], "columns": columns, "parent_columns": parent_columns})
    return keys, links


MULTI_TABLE = "여러 표"


def test_counts(manifest):
    """표마다 붙은 테스트 수 (종류별).

    어느 표의 테스트인지 정하는 순서
        1. attached_node가 있으면 그 표 (모델 · seed에 붙은 테스트)
        2. 없고 depends_on이 하나면 그 표 (원본(source)에 붙은 테스트)
        3. 여러 표를 함께 보는 직접 만든 SQL 테스트(대사 등)는 MULTI_TABLE로 따로 셉니다.
    """
    counts = {}
    for node in manifest["nodes"].values():
        if node["resource_type"] != "test":
            continue
        depends_on = node["depends_on"].get("nodes", [])
        owner = node.get("attached_node") or (depends_on[0] if len(depends_on) == 1 else MULTI_TABLE)
        name = (node.get("test_metadata") or {}).get("name", "직접 만든 SQL 테스트")
        counts.setdefault(owner, {}).setdefault(name, 0)
        counts[owner][name] += 1
    return counts


# ===========================================================================
# DB 읽기
# ===========================================================================

def describe_tables(warehouse, relations):
    """표마다 열(이름 · 타입 · 설명)과 행 수를 DB에서 읽습니다."""
    described = {}
    with warehouse.connect() as connection, connection.cursor() as cursor:
        for unique_id, relation in relations.items():
            schema, name = relation["schema"], relation["name"]
            cursor.execute("""
                SELECT c.column_name, c.data_type, col_description(format('%%I.%%I', c.table_schema, c.table_name)::regclass,
                                                                   c.ordinal_position)
                FROM information_schema.columns c
                WHERE c.table_schema = %s AND c.table_name = %s
                ORDER BY c.ordinal_position""", (schema, name))
            columns = cursor.fetchall()
            if not columns:
                continue
            cursor.execute(f'SELECT count(*) FROM "{schema}"."{name}"')
            described[unique_id] = {**relation, "columns": columns, "rows": cursor.fetchone()[0]}
    return described


# ===========================================================================
# 문서 쓰기
# ===========================================================================

SHORT_TYPES = {"double precision": "float", "bigint": "bigint", "integer": "int", "text": "text",
               "boolean": "bool", "character varying": "text", "numeric": "numeric"}


def node_label(relation):
    return f"{relation['schema']}.{relation['name']}"


def mermaid_id(relation):
    """그림 안의 이름. 표 이름이 이미 스키마로 시작하면(gold_future_stress) 한 번만 씁니다."""
    name = relation["name"]
    if not name.startswith(relation["schema"] + "_"):
        name = f"{relation['schema']}_{name}"
    return re.sub(r"\W", "_", name)


def table_cell_text(text):
    """표 칸에 넣을 수 있게 줄바꿈 · | 를 정리합니다."""
    return re.sub(r"\s+", " ", str(text or "")).replace("|", "/").strip()


def lineage_mermaid(manifest, tables):
    lines = ["```mermaid", "flowchart LR"]
    for schema in SCHEMA_ORDER:
        members = [(uid, t) for uid, t in tables.items() if t["schema"] == schema]
        if not members:
            continue
        lines.append(f'  subgraph {schema}["{schema} · {SCHEMA_ROLES.get(schema, "")}"]')
        for _, table in members:
            lines.append(f'    {mermaid_id(table)}["{table["name"]}<br/>{table["rows"]:,}행"]')
        lines.append("  end")
    for unique_id, table in tables.items():
        for parent_id in resolve_through_ephemeral(manifest, table["depends_on"]):
            if parent_id in tables:
                lines.append(f"  {mermaid_id(tables[parent_id])} --> {mermaid_id(table)}")
    lines.append("```")
    return "\n".join(lines)


def erd_mermaid(tables, keys, links):
    """연결(FK)이 있는 표만 그립니다. 열은 열쇠 · 연결 열만 (모든 열은 아래 표마다 열 목록에)."""
    linked = {link["child"] for link in links} | {link["parent"] for link in links}
    lines = ["```mermaid", "erDiagram"]
    for unique_id in [uid for uid in tables if uid in linked]:
        table = tables[unique_id]
        key_columns = set(keys.get(unique_id, []))
        link_columns = {c for link in links if link["child"] == unique_id for c in link["columns"]}
        types = {name: SHORT_TYPES.get(kind, kind.split()[0]) for name, kind, _ in table["columns"]}
        lines.append(f"  {mermaid_id(table)} {{")
        for column in [name for name, _, _ in table["columns"] if name in key_columns | link_columns]:
            marks = ", ".join(mark for mark, has in (("PK", column in key_columns), ("FK", column in link_columns)) if has)
            lines.append(f"    {types[column]} {column} {marks}".rstrip())
        lines.append("  }")
    for link in links:
        if link["child"] in tables and link["parent"] in tables:
            label = " · ".join(link["columns"])
            # 연결 열이 부모의 열쇠 전체와 같으면 부모 쪽은 '정확히 하나'(||), 아니면 '하나 이상'(}|).
            # 예: 연령별 소비구조는 같은 지역 × 업종에 연령대마다 여러 줄이라 }|
            parent_side = "||" if set(link["parent_columns"]) == set(keys.get(link["parent"], [])) else "}|"
            lines.append(f'  {mermaid_id(tables[link["parent"]])} {parent_side}--o{{ '
                         f'{mermaid_id(tables[link["child"]])} : "{label}"')
    lines.append("```")
    return "\n".join(lines)


def build_document(manifest, tables, generated_at):
    keys, links = keys_and_links(manifest)
    tests = test_counts(manifest)
    ordered = sorted(tables.items(), key=lambda item: (SCHEMA_ORDER.index(item[1]["schema"])
                                                       if item[1]["schema"] in SCHEMA_ORDER else 9, item[1]["name"]))
    total_tests = sum(sum(counts.values()) for counts in tests.values())

    parts = [
        "# 데이터 웨어하우스 데이터 사전",
        "",
        f"> **자동 생성 문서입니다. 손으로 고치지 마세요.** 만든 시각 {generated_at} · "
        "`python -m future_stress.storage.warehouse_docs` (설명은 `dbt/models/*.yml` · `dbt/models/docs.md`에서 고칩니다)",
        "",
        "PostgreSQL `future_stress` 데이터베이스의 스키마 · 표 · 열을 정리한 문서입니다. "
        "원본이 어디서 왔는지는 [데이터 출처](../data_sources.md), 왜 이렇게 만들었는지는 "
        "[15 PostgreSQL](../notes/15_postgresql.md) · [16 dbt](../notes/16_dbt.md)에 있습니다.",
        "",
        "## 1. 한눈에",
        "",
        "| 스키마 | 표 | 종류 | 행 수 | 테스트 | 설명 |",
        "|---|---|---|---:|---:|---|",
    ]
    kinds = {"source": "원본 (파이썬 적재)", "seed": "기준표 (seed)", "model": "dbt 모델"}
    for unique_id, table in ordered:
        test_total = sum(tests.get(unique_id, {}).values())
        parts.append(f"| `{table['schema']}` | [`{table['name']}`](#{table['schema']}{table['name']}) | {kinds[table['kind']]} | "
                     f"{table['rows']:,} | {test_total} | {table_cell_text(table['description'])} |")
    multi_table = sum(tests.get(MULTI_TABLE, {}).values())
    parts += ["", f"표 {len(tables)}개 · 테스트 {total_tests}개 (dbt build가 매번 모두 실행). "
                  f"이 중 {multi_table}개는 여러 표를 함께 보는 직접 만든 SQL 테스트(대사 등, `dbt/tests/`)입니다.", ""]

    parts += [
        "## 2. 계보 (lineage)",
        "",
        "어느 표가 어느 표로 만들어지는지입니다. 화살표 방향으로 데이터가 흐릅니다. "
        "dbt가 SQL 안의 `ref()` · `source()`를 보고 알아낸 관계라서, 모델을 바꾸면 이 그림도 저절로 바뀝니다.",
        "",
        lineage_mermaid(manifest, tables),
        "",
        "## 3. ERD (표 사이 연결)",
        "",
        "선 하나 = 'dbt 테스트로 매번 확인하는 연결'입니다. "
        "`PK`는 겹치면 안 되는 열쇠(unique 테스트), `FK`는 다른 표에 반드시 있어야 하는 값(relationships 테스트)입니다. "
        "여러 열을 합친 열쇠(시도 · 시군구 · 업종코드 · 업종명)는 직접 만든 `composite_relationships` 테스트로 확인합니다.",
        "",
        erd_mermaid(tables, keys, links),
        "",
        "## 4. 표마다 열",
        "",
    ]
    for unique_id, table in ordered:
        parts += [f"### {table['schema']}.{table['name']}", "", table_cell_text(table["description"]) or "(설명 없음)", ""]
        key_text = ", ".join(f"`{c}`" for c in keys.get(unique_id, []))
        test_text = ", ".join(f"{name} {count}" for name, count in sorted(tests.get(unique_id, {}).items()))
        meta = [f"행 {table['rows']:,}"] + ([f"열쇠 {key_text}"] if key_text else []) + ([f"테스트: {test_text}"] if test_text else [])
        parts += [" · ".join(meta), "", "| 열 | 타입 | 설명 |", "|---|---|---|"]
        parts += [f"| `{name}` | {kind} | {table_cell_text(comment)} |" for name, kind, comment in table["columns"]]
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def generate(warehouse=None, manifest_path=MANIFEST_PATH, output_path=OUTPUT_PATH):
    manifest = read_manifest(manifest_path)
    relations = relations_from_manifest(manifest)
    if any(relation["schema"].startswith("synthetic_") for relation in relations.values()):
        raise ValueError("manifest가 합성 데이터(--target synthetic) 기준입니다. "
                         "'docker compose run --rm dbt build'로 원본 기준 manifest를 다시 만든 뒤 실행해 주세요.")
    tables = describe_tables(warehouse or Warehouse.from_environment(), relations)
    document = build_document(manifest, tables, datetime.now().strftime("%Y-%m-%d %H:%M"))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    return output_path, len(tables)


def main():
    argparse.ArgumentParser(description="데이터 웨어하우스 데이터 사전 · 계보 · ERD 자동 생성").parse_args()
    try:
        path, count = generate()
        print(f"{path} 에 표 {count}개 문서를 만들었습니다.")
    except (FileNotFoundError, ValueError) as error:
        raise SystemExit(f"[중단] {error}")
    except psycopg.OperationalError:
        raise SystemExit("[중단] PostgreSQL에 연결할 수 없습니다. 'docker compose up -d'로 띄운 뒤 다시 실행해 주세요.") from None


if __name__ == "__main__":
    main()
