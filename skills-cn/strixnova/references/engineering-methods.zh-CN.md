# 工程方法提交（中文审阅映射）

只有项目基线表明已采用或有条件采用的方法与 affected/unknown 影响相交，或者 WorkItem 正在创建项目时，才读取本文件。随包 DDD 规则只与 `domain`、`architecture`、`interface`、`data` 相交；请求关键词不能激活方法。

是否采用 DDD 由 ProjectEngineeringPolicy 决定，不由目录名决定。状态只有 `adopted`、`conditional`、`not_adopted`、`not_assessed`。DDD 正文位于独立 ProjectDomainModel，实现主张位于独立 ProjectImplementationAlignment；ProjectEngineeringBaseline 只定位其精确采用修订。按 CurrentAction 暴露的目录、确定性闭包和单个 Fact 记录读取，不加载全部 Collection，也不从文档标题推断 bounded context。

Collection 记录已经带 Source 身份、标题、路由摘要、路径和规范形式。先从路由选择一个 Source，再加载 Fact 元数据。通用 Fact `attributes` 必须为空；只有 `context_relationship` 使用固定 from/to/type 字段。项目特定结构写入规范 Fact content，使其仅在需要时加载。

对每个相关的 adopted/conditional 方法恰好提交一个应用。只有已知具体技术、目标、证据和领域 Fact 引用时才选 `applied`；否则使用 `considered_not_applied`。方法本身不会提高 AssuranceBand。每个 planned use 的 `stage` 只能是 `requirements`、`domain_analysis`、`design`、`implementation`、`verification`、`delivery`。

```json
{
  "domain_fact_changes": [{
    "disposition": "retain",
    "target_ref": {
      "schema_version": "strixnova.domain-fact-reference.v1",
      "authority_kind": "project_domain_model",
      "model_id": "MODEL-0123456789ABCDEF",
      "fact_id": "FACT-0123456789ABCDEF",
      "observed_commit": "0123456789abcdef0123456789abcdef01234567"
    },
    "source_path": "docs/domain/sources/work-items.yaml",
    "reason": "当前变更不改变该术语含义。",
    "evidence_refs": ["SRC-001"],
    "lineage": []
  }],
  "method_applications": [{
    "method_id": "ddd",
    "decision": "applied",
    "purpose": "澄清本事项改变的领域边界。",
    "evidence_refs": ["SRC-001"],
    "baseline_refs": ["engineering-policy:method:ddd"],
    "domain_fact_refs": [{
      "schema_version": "strixnova.domain-fact-reference.v1",
      "authority_kind": "project_domain_model",
      "model_id": "MODEL-0123456789ABCDEF",
      "fact_id": "FACT-0123456789ABCDEF",
      "observed_commit": "0123456789abcdef0123456789abcdef01234567"
    }],
    "planned_uses": [{
      "use_id": "DDD-USE-001",
      "stage": "domain_analysis",
      "technique_ids": ["ubiquitous_language", "bounded_context"],
      "purpose": "更新受影响术语和上下文归属。",
      "target_refs": ["impact_scope.affected[0]"],
      "evidence_refs": ["SRC-001"]
    }]
  }]
}
```

DDD 只能使用项目已采用技术：`ubiquitous_language`、`bounded_context`、`context_map`、`domain_invariant_trace`。正式 Fact 引用绑定 `authority_kind`、`model_id`、`fact_id` 与不可变调查提交。`domain_fact_changes` 是评估级项目权威变化，不属于任何方法应用；无论 DDD 是否采用或使用，它都可独立存在。Fact disposition 只有 `retain`、`add`、`update`、`retire`。

更名、移动和不改变含义的澄清保留 Fact ID。同一稳定业务规则的阈值、周期、公式或文字改变属于 `update`，仍保留 Fact ID。只有旧 Fact 已不再表达同一领域概念或角色、由不同后继替代时才是语义替换；替换、拆分、合并使用新的随机 ID，并用 `superseded_by`、`split_into`、`merged_into` 谱系退役旧 Fact。

每个 Fact change 都必须有 `lineage`：`retain`、`add`、`update` 使用 `[]`；只有 `retire` 可以包含替换、拆分或合并关系。条目精确形状为
`{"relation":"superseded_by","target_fact_id":"FACT-0123456789ABCDEF"}`；只有真实关系才使用 `split_into` 或 `merged_into`。程序校验身份、位置、引用、Git 事实和结构闭包，不编写领域含义。

ImplementationAlignment 是由 source-ownership、actual-dependency、target-responsibility 与 deviation 底账组成的一份完整版本化权威，不存在稀疏 `ALIGN-*` 条目合同。计划行为、领域、架构或对齐文件使其过期时，要为完整对齐 manifest 和受影响底账明确计划操作，并把 manifest 操作标为现有 `domain_alignment` 长期产物。Coding Agent 编写经审阅语义；Strixnova 只校验绑定、覆盖、精确修订和可重复漂移事实。

只有 WorkItem 改变项目长期方法决定时才使用 `adoption_change`。此时把工程政策计划为 `quality_policy`，并把工程基线作为普通精确引用更新；基线不是兜底长期产物。

采用或条件采用 DDD 还要求独立的领域模型与实现对齐路径、Fact add/update、完整实现对齐 create/update 以及项目采用的 DDD 技术。现有基线还没有 DDD 路径时，恰好声明一个 `domain_model` 和一个 `domain_alignment` 长期产物操作；Strixnova 从操作目标取得路径，不再要求重复字段。新项目必须诚实选择每个随包方法的状态，包括 `not_assessed`，并始终建立独立 ProjectArchitectureDescription。不得建立方法专属工作流、关键词路由、合规分数、代码图或自动重构。
