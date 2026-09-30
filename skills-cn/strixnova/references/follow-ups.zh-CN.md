# 明确延期问题的后续承接

结果留下真实未来承诺、新方向承接旧问题，或负责人查询待办时读取。沿用现有 WorkItem、实际结果和确认。程序不从文字猜承诺，不调度 Agent，不建立另一个问题系统。

## 留下明确处置

当前范围的问题在当前事项修复。剩余限制区分接受并结束跟进、承诺以后处理；只有明确处置才写入 `follow_up_items`，普通证据或范围说明仍可保留在 `limitations`。

```json
{"follow_up_id":"FOLLOWUP-0123456789ABCDEF","limitation_refs":["limitations[0]"],"disposition":"deferred","reason":"负责人选择下次扩容前核对容量。","responsible_party":"项目维护者","due_on":null,"review_condition":"下次扩容前","completion_criteria":"按已约定负载测量并处置原限制。"}
```

`deferred` 必须有责任方、日期或业务复查条件及完成标准。`due_on` 使用 YYYY-MM-DD，与查询机器本地日期比较；业务条件由 Agent 根据证据判断。负责人接受限制并结束跟进时用 `accepted_limitation`，四个责任及时间安排字段均为 null。同一结果中一条限制不得有竞争处置。生成不含语义的稳定身份，在未接受候选的修订中保留；接受后不得用于另一份结果。

在原有实际结果确认点解释处置；接受前只是候选，不增加确认点，也不要求立即创建子事项。后来处置不改写原决定。

## 查询和承接

```text
strixnova status --project-dir <project> --follow-ups --limit 25
strixnova status --project-dir <project> --follow-ups --include-closed
strixnova status --project-dir <project> --follow-ups --limit 25 --cursor <next_cursor>
```

该入口只读本地已接受记录，无需 Git 采用或 CurrentAction，也不初始化状态。每页最多 100 条，绑定快照、筛选、页大小和查询日期；快照变化后重新查询。方向或评估阶段也可按需读取 `project.follow_ups`，不在每个动作预加载完整列表。只覆盖明确接受的条目，不从旧版本推断义务，也不以空列表证明没有技术债。

已授权的事项通过方向中现有 `follows_up` 关系增加 `follow_up_refs`，原样复制查询返回的引用：

```json
{"target_work_item_id":"WI-20260910-EXAMPLE","relation_type":"follows_up","reason":"处理原容量限制。","follow_up_refs":[{"work_item_id":"WI-20260910-EXAMPLE","result_version":6,"follow_up_id":"FOLLOWUP-0123456789ABCDEF"}]}
```

示例身份和版本不用于实际请求。原结果必须已接受，条目仍开放。没有精确引用的普通关系不承诺解决目标限制。已有事项需要承接时，也通过同一方向修订路线处理。

## 交代后续结果

展示结果前重新查询原条目。对已确认方向中的每项精确引用，提交一项 `follow_up_results`：

```json
{"follow_up_ref":{"work_item_id":"WI-20260910-EXAMPLE","result_version":6,"follow_up_id":"FOLLOWUP-0123456789ABCDEF"},"expected_version":7,"outcome":"resolved","rationale":"记录的测量回应原已约定限制。","evidence_refs":["delivered_outcomes[0]"],"limitation_refs":[]}
```

`expected_version` 复制条目的当前版本。结果为 `resolved`、`partially_resolved`、`still_open` 或 `accepted_limitation`。已解决需要实际依据，其他结果必须精确引用剩余限制。程序检查引用、记录版本和结构，不判断 Agent 的因果或业务判断是否正确。

后续实际结果被接受后，派生视图才改变处置。子事项完成或取消都不会自行关闭原问题。其他已接受结果先推进了条目时，`follow_up_conflict` 或 `follow_up_not_open` 会在写入前拒绝过期候选；读取新依据，通过原有纠正或重规划路线修订并重新展示。
