# 安装态实现对齐工作流（中文审阅映射）

优先按 [prepared-input.md](prepared-input.zh-CN.md) 使用准备接口：`alignment prepare --output` 保存一次绑定，检查、捕获和候选写入沿用 `--prepared`。`alignment inspect --output` 自动汇集所选准备包的分页，再用 `action inspect` 读取材料。下文命令示例说明低层合同，不要求重复抄写元数据或搬运游标；外部执行仍需明确授权。

> 本文件只供项目负责人审阅正式 Skill 的含义，不是可安装 Skill，不取得运行权威。

仅当当前 WorkItem（建设事项）处于 `implementing`，且当前已确认
EngineeringPlan（工程方案）的聚焦实施切片恰好拥有或延续一个
`domain_alignment` 操作时，才使用本工作流。该切片还必须计划实现对齐根文件、四份从属底账和项目工程基线。本工作流观察实现事实并写入可恢复的草稿；它不会确认或采用长期权威，不改变 WorkItem 版本或状态，也不证明语义正确。

## 公开接口

在当前切片最后一项正式验证及其后置判断之前，完成所需代码和实现对齐写入。对齐描述由
适用证据支持的实际实现，不是另一份等待最终验证回执的进度账。开发证据如实记录，最终
回执状态保留在既有验证记录；不能只因最终回执尚未产生，就把实际实现标为未完成。
最后一次后置判断可能结束切片，此后不能再准备尚未完成的对齐写入。真实实现缺口仍会
阻止完成，不能隐藏缺口或伪造重测标志来重开已结束切片。

安装后只有四个复核与写入命令：

```text
strixnova alignment prepare
strixnova alignment inspect
strixnova alignment capture-external
strixnova alignment write-candidate
```

`strixnova alignment gc` 是项目负责人明确发起的独立缓存维护命令，不属于复核/写入顺序，也不使用 WorkItem 绑定参数。

每次调用都使用同一绑定参数：

```text
--work-item-id <ID> --version <current-version>
```

位于项目根目录时省略 `--project-dir`，从其他目录操作时才添加。非 ASCII 输入按主 Skill 的说明使用系统临时 UTF-8 `@file`。stdout 始终是一行 JSON，读取其中的
`alignment`。不得查看安装包源码或测试来猜合同。

## 1. 准备内容寻址观察包

已有已确认实现对齐时，只提交新修订身份及其精确取代的现行修订：

```json
{
  "schema_version": "strixnova.implementation-alignment-preparation-request.v1",
  "alignment_revision_id": "ALIGNREV-<16 uppercase hex>",
  "supersedes_revision_id": "ALIGNREV-<current 16 uppercase hex>"
}
```

不要重复提交现行观察范围、受管源码范围或产物路径；Strixnova 会自行读取并保留。若现有修订已经是 `draft`，省略 `--input` 即可继续同一草稿。若现有修订为已确认或其他非草稿状态，则必须使用上面的最小请求。

只有项目首次建立实现对齐时，才增加下面三个字段。其嵌套结构由
`strixnova.project-implementation-alignment.v1` 精确规定：

```json
{
  "schema_version": "strixnova.implementation-alignment-preparation-request.v1",
  "alignment_revision_id": "ALIGNREV-<16 uppercase hex>",
  "supersedes_revision_id": null,
  "observation_scopes": [],
  "governed_source_scopes": [],
  "artifact_paths": {
    "source_ownership": "<planned relative path>",
    "actual_dependencies": "<planned relative path>",
    "target_responsibilities": "<planned relative path>",
    "deviations": "<planned relative path>"
  }
}
```

这里的空数组只是展示外层结构；真实首次请求至少包含一个有效观察范围和一个受管源码范围。

调用：

```text
strixnova alignment prepare --work-item-id <ID> --version <N> --input @request.json
```

结果包含：

- `preparation_ref`：供后续调用使用的不可变内容与路径绑定；
- 必需和可选语义决定数量；
- 覆盖状态，以及计划内外部观察是否可用、是否必要；
- `semantic_content_machine_proven: false`。

若 `external_capture_required` 为 true，先保留该引用并执行第 2 节，不检查旧准备包；只检查 capture 返回的更新准备包。否则把完整返回引用作为唯一字段写入 `inspection.json`：

```json
{"preparation_ref":{}}
```

调用逻辑检查入口：

```text
strixnova alignment inspect --work-item-id <ID> --version <N> \
  --input @inspection.json
```

按顺序复核返回的 `items`。上下文记录包含冻结的工作绑定、长期权威身份、架构模块/关系/约束、现有实现对齐上下文、受管范围、观察覆盖和 provider 回执；每个 `semantic_decision` 记录包含一项精确决定合同。若 `next_cursor` 不是 null，就在同一命令增加 `--cursor <next_cursor>`，直到返回 null。游标必须当作不透明值，不得跳页。默认分页已有界限；只在需要缩小上下文或当前上下文允许时使用 `--limit`，且不得超过公开上限。不得读取或修改 `.strixnova/artifacts/implementation-alignment`；其中的内容寻址清单、组件和分页都属于私有实现。

## 2. 只在必要时捕获已计划外部 provider

内置静态 provider 在 `prepare` 中运行。Rust、Go、TypeScript 和其他内置支持的范围可能已经完整。C#、C++、未知语言或需要编译器特定分析的配置可能保持
`partial`、`unavailable` 或 `failed`，除非已确认 EngineeringPlan 包含精确外部 provider 计划。

仅当 `external_capture_required` 为 true 且已确认方案确实包含该 provider 时，原样提交准备引用：

```json
{"preparation_ref":{"schema_version":"strixnova.implementation-alignment-preparation-ref.v1","artifact_kind":"preparations","artifact_id":"ALIGNPREP-<16 uppercase hex>","path":"<returned path>","content_sha256":"<returned sha256>"}}
```

调用：

```text
strixnova alignment capture-external --work-item-id <ID> --version <N> \
  --authorize-external --input @capture.json
```

`--authorize-external` 只授权本次调用。CLI 故意不接收 provider argv、可执行文件、材料散列、超时、glob 或 `process_policy`；argv 以及每个可执行文件、入口脚本、配置和支撑文件的 SHA-256 身份必须已在项目负责人确认的 EngineeringPlan 中。Strixnova 在进程启动前重新核对这些字节并写入回执。之后只使用本命令返回的更新版 `preparation_ref`，把它写入 `inspection.json` 并从第一页开始检查；旧准备包的游标不能用于更新后的准备包。

不要为了把覆盖状态改成 `complete` 而虚构外部 provider。覆盖不完整也可以作为诚实草稿证据。

## 3. 只提交语义决定并写入草稿

逐项处理检查结果中 `record_kind` 为 `semantic_decision` 的记录，以其 `value` 作为决定目录项：

- 提交所有 `required: true` 项；
- 若可选项的 `facts.previous` 语义仍正确，则省略；
- 只有确实修改原语义时才提交可选项；
- 精确复制 `decision_ref`，value 只能包含 `required_value_fields` 列出的字段；
- 根据代码、项目文档、用户讨论和工程判断确定含义，不能只看文件名；
- 对 `remove_*` 项显式提交 `accepted: true` 和非空 `rationale`。

Strixnova 负责填充观察身份、路径、散列、关系事实、长期权威引用、回执、代码版本和修订绑定。语义决定不得重复或篡改这些机械事实。

一次提交：

```json
{
  "schema_version": "strixnova.implementation-alignment-candidate-decisions.v1",
  "preparation_ref": {},
  "decisions": [
    {
      "decision_ref": "ALIGNDECISION-<16 uppercase hex>",
      "value": {}
    }
  ],
  "deviations": [],
  "unresolved_items": []
}
```

上面的空对象用于说明正式合同。优先按 [prepared-input.md](prepared-input.zh-CN.md) 使用 `alignment prepare --output` 和 `--prepared`，由程序传递完整 `preparation_ref`；每个决定 value 必须精确匹配目录字段。非空 `deviations` 与 `unresolved_items` 使用当前输入 Schema。

调用：

```text
strixnova alignment write-candidate --work-item-id <ID> --version <N> \
  --input @candidate.json
```

Strixnova 会重新核对 WorkItem、已确认方案、聚焦切片、工作树、准备包散列、受管文件集合和字节，以及 `prepare` 时记录的六个候选目标是否存在和实际字节散列。每个受管源码文件必须精确匹配一个受管作用域，不能按列表先后决定归属。随后先落盘事务日志和旧文件副本，再把实现对齐根、四份底账和工程基线作为一个可恢复文件事务替换并重新校验完整候选。最终校验失败会恢复每个旧文件；进程崩溃或断电发生在提交前时，下次进入实现对齐会根据持久日志恢复。若期间出现第三方编辑，程序会停止而不会猜测覆盖。

必须按窄含义解释结果：

- `candidate_valid: true` 只证明草稿通过确定性合同和跨文件校验；
- `complete_alignment: true` 还表示观察覆盖完整、owned 源码已对齐、依赖分类通过、目标责任已实现，且没有偏离或未解决项；
- `candidate_status: draft` 表示候选尚未确认或采用；
- `semantic_content_machine_proven: false` 始终表示程序没有证明 Agent 的领域或架构判断。

之后继续既有验证与 ActualResult（实际结果）流程。不能因为候选结构有效就调用
`strixnova confirm`。ImplementationAlignment（实现对齐）仍须绑定项目负责人独立接受的实际结果才能采用。

## 恢复与停点

- `alignment_preparation_stale`：丢弃旧包，针对当前 WorkItem 和工作树重新执行 `prepare`。
- `alignment_governed_scope_ambiguous`：把受管源码范围改成互不重叠，不能依赖列表顺序挑选归属。
- `alignment_transaction_recovery_failed`：立即停止，保留事务目录，先解决错误中报告的文件冲突再重试。
- `alignment_candidate_paths_unplanned`：不得扩大写入范围；重新规划，让聚焦切片显式拥有全部六个候选路径。
- `alignment_revision_request_required`：形成最小新修订请求，不手工修改确认元数据。
- `external_observation_not_planned`：保留诚实的不完整覆盖，或重新规划 provider；不得临时传入命令。
- 语义决定错误：重新检查同一准备包，只纠正指定决定。
- 当代码和文档不能确定归属、架构分类、责任状态、偏离接受或重要未知时，停止并让项目负责人作真实决定。

准备、捕获和组件文件不可变且会按内容去重，不得手工删除这些目录。只有项目负责人明确要求回收本地缓存空间时，才先运行：

```text
strixnova alignment gc --dry-run
```

该命令只报告所有保留 preparation 与 capture 清单均未引用的组件；它不会删除 preparations、captures、transactions 或长期权威。负责人接受这次精确预览后，原样提交其中的 `orphan_set_sha256`：

```text
strixnova alignment gc --apply \
  --expected-orphan-set-sha256 <orphan_set_sha256>
```

若孤立集合发生变化，应用会被拒绝，必须重新 dry-run。普通实现对齐过程中不得调用任一维护模式，除非项目负责人明确要求缓存维护。


仓库限定观察字段与索引见[实现对齐精确合同](implementation-alignment-artifact-contracts.zh-CN.md)，基线布局见[长期权威起草](authority-authoring.zh-CN.md)。不从旧观察重建当前合同。
