# 重新规划与集成判断（中文审阅映射）

已有方向或评估需要修订时，按 [prepared-input.md](prepared-input.zh-CN.md) 使用精确 `revision_bases`，明确给出变化和 `keep_rest` 判断，由程序生成完整修订。“其余适用”仍是 Agent 的语义判断，不会继承早前负责人接受。

只读取与 `CurrentAction.input_kind` 匹配的章节。

## 针对性修正后仍重复失败

同一重要失败在一次针对性修正后重现时，先停止该重试序列，重新读取控制规则、当前实施
材料及原始观察结果。区分产品缺陷、方案错误、验收驱动错误、Agent 输出错误和环境阻断；
证据不足时保留原因未知。每个后续步骤要说明能改变或证明什么实际行为。程序已经持有的
事实不再让 Agent 重抄，不通过增加格式例外让语义审阅通过。

已确认操作和含义范围内的修复可以在当前切片继续，不新增产品决定。新事实使操作、依赖、
验证或范围失效时沿既有 replan 路径处理；不能降低原规则，也不把是否继续遵守它重新交给
负责人选择。确需改变上游决定时才交还相应决定权。`review_subject_changed` 要求重评受影响
内容，不能只给原结论换一个新身份。

沿用已经说明的调查和验证预算；耗尽时保留原失败、已尝试修正、仍未知原因及下一责任人，
停止受阻场景并继续其他已授权工作。不要重建无关夹具、扩大验收范围、追加审阅者或反复
运行已通过测试来凑全绿。修复后的发现按当前内容重评，未解决项沿用既有审阅、方案及结果
记录保留，不建立新账本或确认点。

## Replan（重新规划）

新事实使已确认方案失效时提交：

```json
{"schema_version":"strixnova.replan-request.v1","reasons":["specific changed fact"]}
```

只有工程事实变化时，保留 `assessment_id`、增加 `assessment_revision` 并沿用当前 `direction_ref`。目标、范围、取舍、验收或 WorkItem 关系变化时，先提交完整修订方向并重新确认，再让修订评估绑定新方向版本。

`CurrentAction.action_type=revise_direction` 表示程序已经按版本、引用或覆盖证明原产品上下文绑定过期。读取列出的旧方向和当前产品上下文，只修改受影响决定；证据和含义仍有效的用户决定不要求重答。修订后的完整卡片继续使用现有方向确认点，不新增关口。

修改前先确定失效层：

- 产品目的、范围或成功含义变化：回到方向或产品定义；
- 术语、决定权、规则、不变量或场景含义变化：回到领域模型；
- 目标责任、依赖方向或领域事实承载变化：回到目标架构；
- 上游仍正确，只是操作、ImplementationSlice、风险或验证不完整：形成新 EngineeringAssessment 修订；
- 已确认操作和含义内可修复的实现问题：在当前切片修复并复验；新事实使方案失效时，停止当前切片，完成重新规划后才执行后续依赖切片。

已采用上游长期权威变化时，重做 `authority_change_set`、全部下游处置、`semantic_review`、受影响 `implementation_slices` 和 `owner_view`。依据仍成立的决定继续复用，不重新开始形式化追问。

## Target advance（目标分支前进）

查看调查提交与目标提交之间的原生 Git diff，只提交语义判断：

```json
{
  "schema_version": "strixnova.target-advance-assessment.v1",
  "semantic_impact": "affected|unaffected",
  "reason": "..."
}
```

## Git conflict（原生冲突）

解决原生 Git 内容冲突后，说明必须重测什么：

```json
{
  "user_visible_result_changed": false,
  "confirmed_direction_or_plan_changed": false,
  "reason": "...",
  "retest_command_ids": ["VC-001"]
}
```

`retest_command_ids` 只列实际受冲突解决影响的已计划命令。方案有命令但本冲突与它们无关时可以为空，理由中说明判断。Strixnova 会把判断绑定到用户已接受的精确文件快照，不自行推断命令语义相关性。

不得用无关命令、失败结果或 `not_run` 解锁合并。


## 恢复已记录副作用

遇到 `input_kind=resume_external_effect` 时，读取 `pending_effect`，沿用原仓库、执行位置和 CurrentAction 的 `intent`：

| 意图 | 继续方式 |
|---|---|
| `verify` | 按[验证规程](verification.zh-CN.md)使用原 `command_id` 和 `mode=run` 接收既有回执，不在其他 shell 中另跑命令。 |
| `delivery` | 按当前输入合同和[交付规程](delivery.zh-CN.md)继续原 Git 或文件操作。 |
| `cancel` | 按已记录的取消决定和[确认与取消](confirmation-and-cancel.zh-CN.md)继续，不推断新的丢弃决定。 |

取消前先处理仍在执行或结果未知的操作。执行未收口时，按[收口未结束执行](history-and-upgrade.zh-CN.md#收口未结束执行)先确定真实停止状态。部分取消保留已合入内容和未交付工作，不撤销已合入结果；整体结果变化沿用原有重新展示和接受流程。


## 部分合入后的重规划

事项尚未完成时，新整体方案可以要求已合入仓库再次修改。保留此前贡献，按新方案准备工作区并形成新的结果接受。保留的原生合入冲突仍以目标检出目录作为实施位置：读取 `repository_deliveries[].git.conflict_resolution`，使用对应记录的 `repository`，其他仓库保留各自工作区。
