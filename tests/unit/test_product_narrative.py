from __future__ import annotations

from pathlib import Path
import re
import subprocess
import tomllib

import strixnova
import yaml
from strixnova.project_domain_model import ACTIVE_FACT_STATUSES


PROJECT_ROOT = Path(__file__).parents[2]
PACKAGE_SUMMARY = "帮助非专业项目负责人做好本地软件工程全链路治理的工具"
PUBLIC_PURPOSE = "帮助非专业项目负责人做好软件工程全链路治理的本地工具"
MODULE_DESCRIPTION = (
    "Strixnova —— 帮助非专业项目负责人做好软件工程全链路治理的本地工具。"
)
ROLE_SPLIT = (
    "项目负责人作出决定、智能编码代理形成工程语义并实施、程序治理确定性状态"
)
PUBLIC_ROLE_SPLIT = (
    "项目负责人负责说明预期效果、作出重大取舍并接受实际结果；"
    "智能编码代理负责调查、形成有依据的语义候选、实施并解释真实证据；"
    "程序只处理结构、版本、状态、确定性规则、本地版本生命周期和真实回执"
)
SUPPORTED_AGENT_CAPABILITY_ID = "CAPABILITY-FDB7B365AFC84F66"
SUPPORTED_AGENT_FACT_ID = "FACT-C397E6F65C5E74B7"


def _without_layout_whitespace(value: str) -> str:
    return "".join(value.split())


def _current_domain_projection() -> tuple[dict, list[tuple[str, dict]]]:
    model = yaml.safe_load(
        (PROJECT_ROOT / "docs" / "domain" / "model.yaml").read_text(
            encoding="utf-8"
        )
    )
    pending = list(model["root_collection_paths"])
    collection_paths: list[str] = []
    source_paths: list[str] = []
    while pending:
        collection_path = pending.pop(0)
        collection = yaml.safe_load(
            (PROJECT_ROOT / collection_path).read_text(encoding="utf-8")
        )
        collection_paths.append(collection_path)
        pending.extend(collection["child_collection_paths"])
        source_paths.extend(item["path"] for item in collection["sources"])

    assert len(collection_paths) == len(set(collection_paths))
    assert len(source_paths) == len(set(source_paths))
    facts: list[tuple[str, dict]] = []
    for source_path in source_paths:
        source = yaml.safe_load(
            (PROJECT_ROOT / source_path).read_text(encoding="utf-8")
        )
        facts.extend((source_path, fact) for fact in source["facts"])
    assert len(facts) == len({fact["fact_id"] for _, fact in facts})
    model["_projection_collection_count"] = len(collection_paths)
    model["_projection_source_count"] = len(source_paths)
    return model, facts


def test_public_source_identity_describes_a_governance_tool() -> None:
    pyproject = tomllib.loads(
        (PROJECT_ROOT / "strixnova" / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["project"]["description"] == PACKAGE_SUMMARY
    assert strixnova.__doc__ == MODULE_DESCRIPTION

    package_readme = (PROJECT_ROOT / "strixnova" / "README.md").read_text(
        encoding="utf-8"
    )
    assert PUBLIC_PURPOSE in package_readme
    assert PUBLIC_ROLE_SPLIT in package_readme
    assert "不会启动、调用、调度或管理智能编码代理" in package_readme


def test_supported_agent_reading_table_is_derived_from_current_authorities() -> None:
    product = yaml.safe_load(
        (PROJECT_ROOT / "docs" / "product" / "definition.yaml").read_text(
            encoding="utf-8"
        )
    )
    domain = yaml.safe_load(
        (
            PROJECT_ROOT
            / "docs"
            / "domain"
            / "sources"
            / "capabilities.yaml"
        ).read_text(encoding="utf-8")
    )
    product_capability = next(
        item
        for item in product["capabilities"]
        if item["capability_id"] == SUPPORTED_AGENT_CAPABILITY_ID
    )
    domain_fact = next(
        item
        for item in domain["facts"]
        if item["fact_id"] == SUPPORTED_AGENT_FACT_ID
    )
    reading_lines = (
        PROJECT_ROOT
        / "docs"
        / "领域模型阅读版"
        / "Strixnova领域模型完整阅读版.md"
    ).read_text(encoding="utf-8").splitlines()
    matching_rows = [
        line
        for line in reading_lines
        if line.startswith(f"| [{SUPPORTED_AGENT_CAPABILITY_ID}")
    ]

    assert domain_fact["status"] == "draft"
    assert product["revision"]["status"] == "draft"
    assert domain_fact["product_capability_ids"] == [SUPPORTED_AGENT_CAPABILITY_ID]
    assert len(matching_rows) == 1
    row = _without_layout_whitespace(matching_rows[0])
    assert f"[{product_capability['title']}]" in row
    assert _without_layout_whitespace(product_capability["description"]) in row
    assert _without_layout_whitespace(domain_fact["content"]["definition"]) in row


def test_domain_reading_projection_preserves_fact_identity_status_and_indexes() -> None:
    model, sourced_facts = _current_domain_projection()
    product = yaml.safe_load(
        (PROJECT_ROOT / "docs" / "product" / "definition.yaml").read_text(
            encoding="utf-8"
        )
    )
    reading_path = (
        PROJECT_ROOT
        / "docs"
        / "领域模型阅读版"
        / "Strixnova领域模型完整阅读版.md"
    )
    reading = reading_path.read_text(encoding="utf-8")
    current = [fact for _, fact in sourced_facts if fact["status"] in ACTIVE_FACT_STATUSES]
    historical = [fact for _, fact in sourced_facts if fact["status"] not in ACTIVE_FACT_STATUSES]

    assert model["revision"]["status"] == "draft"
    assert model["revision"]["revision_id"] in reading
    assert f"包含 {len(current)} 条现行事实和 {len(historical)} 条历史事实" in reading
    assert (
        f"本说明书覆盖 {model['_projection_collection_count']} 个领域集合、"
        f"{model['_projection_source_count']} 个正式来源、{len(current)} 条现行事实和 "
        f"{len(historical)} 条历史记录。"
    ) in reading

    index_rows: dict[str, list[str]] = {}
    for line in reading.splitlines():
        if "（领域事实标识） |" not in line:
            continue
        match = re.search(r"`(FACT-[A-F0-9]{16})`", line)
        assert match is not None, line
        index_rows.setdefault(match.group(1), []).append(line)

    status_labels = {
        "draft": "草稿",
        "ready_for_confirmation": "待确认",
        "confirmed": "已确认",
        "superseded": "已被取代",
        "retired": "已废止",
    }
    for _, fact in sourced_facts:
        fact_id = fact["fact_id"]
        assert reading.count(f'<a id="{fact_id}"></a>') == 1, fact_id
        assert len(index_rows.get(fact_id, [])) == 1, fact_id
        cells = [cell.strip() for cell in index_rows[fact_id][0].split("|")]
        assert cells[4] == status_labels[fact["status"]], fact_id

    source_counts: dict[str, tuple[int, int]] = {}
    for source_path, fact in sourced_facts:
        active, old = source_counts.get(source_path, (0, 0))
        if fact["status"] in ACTIVE_FACT_STATUSES:
            active += 1
        else:
            old += 1
        source_counts[source_path] = (active, old)
    for source_path, (active, old) in source_counts.items():
        link = "../" + source_path.removeprefix("docs/")
        assert f"]({link}) | {active} | {old} |" in reading, source_path

    appendix = reading.split("### 附录二：产品能力反向索引", 1)[1].split(
        "### 附录三：领域事实索引", 1
    )[0]
    for capability in product["capabilities"]:
        heading = f"#### {capability['title']}"
        section = appendix.split(heading, 1)[1].split("\n#### ", 1)[0]
        expected = {
            fact["fact_id"]
            for _, fact in sourced_facts
            if fact["status"] in ACTIVE_FACT_STATUSES
            and capability["capability_id"] in fact["product_capability_ids"]
            and fact["kind"] != "product_capability"
        }
        actual = set(re.findall(r"#(FACT-[A-F0-9]{16})", section))
        assert actual == expected, capability["capability_id"]
        assert f"关联领域内容共 {len(expected)} 条" in section

    capability_facts = {
        fact["product_capability_ids"][0]: fact
        for _, fact in sourced_facts
        if fact["status"] in ACTIVE_FACT_STATUSES and fact["kind"] == "product_capability"
    }
    for capability in product["capabilities"]:
        rows = [
            line
            for line in reading.splitlines()
            if line.startswith(f"| [{capability['capability_id']}")
        ]
        assert len(rows) == 1, capability["capability_id"]
        row = _without_layout_whitespace(rows[0])
        assert _without_layout_whitespace(capability["description"]) in row
        assert _without_layout_whitespace(
            capability_facts[capability["capability_id"]]["content"]["definition"]
        ) in row


def test_current_documents_use_the_same_role_split() -> None:
    paths = [
        PROJECT_ROOT / "docs" / "engineering" / "method-sources.md",
    ]

    for path in paths:
        assert ROLE_SPLIT in path.read_text(encoding="utf-8")


def test_tracked_tree_contains_no_retired_strixnova_identity() -> None:
    retired_identity_pattern = "|".join(
        [
            "虚拟" + "软件工程负责人",
            "虚拟" + "工程团队",
            "虚拟" + "软件工程团队",
        ]
    )
    result = subprocess.run(
        ["git", "grep", "-n", "-I", "-E", retired_identity_pattern, "--", "."],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 1, result.stdout
