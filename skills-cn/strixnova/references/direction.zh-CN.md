# 方向提交（中文审阅映射）

仅在 `CurrentAction.input_kind=direction` 时读取本文件。使用用户自己的词汇，不为满足字段而虚构范围。

提交前先通过 `strixnova next --record` 读取 `CurrentAction.input_contract_ref`。返回的公开合同是载荷结构权威；本文件只说明如何形成语义内容。

若 CurrentAction 列出 `project.direction_context`，同一步读取它。该记录完整而紧凑地投影当前已采用的产品目的、阶段、能力目录、非目标和约束，但不推荐相关能力，也不作相关性排序；程序不会替 Agent 决定哪个能力与请求相关。

## 提交前按比例澄清

用户最初愿望是证据，但不自动等于完整方向。只澄清足以安全确认的内容：

1. 分开可调查项目事实与用户决定。代码、项目规则和现有行为能回答时由 Agent 自行检查；不要让用户识别文件、架构、测试、DDD 术语或 Agent 可判断的实现细节。
2. 只找会实质改变目标、范围、非目标、约束、验收或关键取舍的未决决定。后续工程评估细节不要提前询问。
3. 一次只问一个决定。先给推荐答案，再用普通语言说明用户可见效果或取舍；先解决上游选择，再问依赖它的问题。
4. 愿望已经安全且具体时不问仪式性问题。能够诚实说明六组方向内容后立即停止，不遍历全部可能分支，也不要求先理解整个项目。
5. 澄清留在普通宿主对话中，不建立第二套 Strixnova 讨论状态，不逐轮提交。方向准备好后一次提交；仍有重要决定未闭合时，提交 `ready_for_confirmation=false` 和具体 blockers。用户尚未回答时，绝不能把推荐答案写进待确认方向。

把推荐选择和影响放在当前唯一未决问题旁边。依据仍成立时复用已有回答；确实需要新决定时，说明发生变化的假设。例如仅导出范围未定时：“建议先导出当前筛选结果，这样文件与眼前列表一致；导出全部数据会包含未显示记录。你希望导出当前结果还是全部数据？”不要附带询问可自行调查的文件位置或实施细节。这次澄清仍不接受后来形成的完整方向。

## 绑定当前产品决定

已有采用产品权威的项目，Agent 必须：

1. 从完整目录中选择至少一个真实相关的 `capability_ref`；
2. 对每个 guardrail 恰好处置一次，使用 `applies`、`not_applicable` 或 `reconsider`，并给出项目针对性理由；
3. 只记录实质支撑当前方向的假设，以及会触发重新考虑的事实；
4. 精确复制当前 `context_ref`。

程序只校验新鲜度、身份、引用存在、唯一性和 guardrail 完整覆盖，不判断能力是否语义相关、理由是否有说服力或假设是否明智。产品上下文变化会使旧方向过期；评估、实施或实际结果接受前，必须基于新上下文重新形成方向。`CurrentAction.action_type=revise_direction` 是确定性恢复路径：读取旧方向、下游方案和新的完整 `project.direction_context`，只解释变化，并复用依据仍成立的用户决定。修订提交会原子记录精确失效事实和替代候选，再进入普通方向确认，不增加用户关口。

`reconsider` 不会取消现行产品决定。在新 ProductDefinition 候选经过评估、独立确认和采用前，原 guardrail 继续约束。跟随 `reconsider` 的工程评估必须把 `product_scope` 标为 affected 或 unknown，并计划产品候选。

没有已采用 ProductDefinition 的项目使用 `context_ref: null`，能力与 guardrail 列表为空，不得虚构产品引用。

方向确认前，用一张普通语言卡片展示目标、范围内与范围外结果、验收、重要约束和取舍，以及仍未解决的 blocker。这是按比例引导，不是强制穷举访谈。

## 为每个方向条目建立稳定身份

需求、约束、验收条件或行为例子首次出现时，分别创建随机身份：`DIRREQ-`、`DIRCON-`、`DIRACC-` 或 `DIREX-` 后接 16 位大写十六进制。身份不是内容散列，也不能从数组位置生成。

修订已确认方向时，按含义而不是文字或顺序判断：

- 只重排或澄清措辞且含义未变时，保留原身份；
- 含义被替换、拆分或合并时，使用新身份；
- 一个身份从后续已确认方向退出后，绝不能恢复；
- 每项验收条件通过 `requirement_refs` 列出适用的全部 `DIRREQ-*`，且每条当前需求至少被一项验收条件覆盖。

向用户展示完整方向修订时，用普通语言解释哪些含义保留、退出或被替代，不要求用户管理原始 ID。程序只校验身份格式、唯一性、引用闭合、需求覆盖和退出后不复活；程序不判断语义是否相同，也不判断验收是否充分。确认仍然覆盖完整方向修订；新的 `direction_version` 仍会使全部旧评估、方案、实施记录和验证结果失效。

不要把原始 `context_ref`、能力 ID、决定 ID 或散列当作用户能理解的含义。用普通语言解释所选能力、每个 guardrail 的处置和重要假设；内部引用只在载荷中机械携带。

每项验收必须填写 `behavior` 处置。可观察行为变化使用 `required` 和具体例子；其范围、依据和后续核验见[行为例子与核验](behavior-examples.zh-CN.md)。纯说明或不改变行为的机械修改可以使用 `applicability=not_applicable` 并填写具体 `reason`；带原因的 `undetermined` 只允许在有阻碍的草稿中，不能进入待确认方向。例子并入原有方向卡和确认。

```json
{
  "direction": {
    "schema_version": "strixnova.direction-decision.v1",
    "decision_context": {
      "context_ref": null,
      "capability_refs": [],
      "guardrail_dispositions": [],
      "assumptions": []
    },
    "goal": "库存不足时拒绝预留。",
    "scope": [
      {
        "requirement_id": "DIRREQ-0123456789ABCDEF",
        "statement": "拒绝库存不足的请求并保持库存不变。"
      }
    ],
    "non_goals": [],
    "constraints": [
      {
        "constraint_id": "DIRCON-0123456789ABCDEF",
        "statement": "库存不能变成负数。"
      }
    ],
    "acceptance": [
      {
        "acceptance_id": "DIRACC-0123456789ABCDEF",
        "statement": "因库存不足拒绝请求后，库存保持不变。",
        "requirement_refs": ["DIRREQ-0123456789ABCDEF"],
        "behavior": {
          "applicability": "required",
          "examples": [{
            "example_id": "DIREX-0123456789ABCDEF",
            "title": "拒绝超过可用库存的预留",
            "given": ["可用库存为 2 件"],
            "when": "调用方预留 3 件",
            "then": ["请求被拒绝", "可用库存仍为 2 件"],
            "basis_refs": ["direction.requirement:DIRREQ-0123456789ABCDEF"]
          }]
        }
      }
    ],
    "tradeoffs": [],
    "work_item_relations": []
  },
  "ready_for_confirmation": true,
  "blockers": []
}
```

方向尚不安全时把 `ready_for_confirmation` 设为 false，并提供具体 blockers。`work_item_relations` 可选；只有用户或已知项目事实指向真实目标时才填写，不扫描全部 Authority 历史猜目标。关系类型：

- `related_to`：确有一般关联且无更精确类型；
- `part_of`：本事项属于目标的大事项；
- `depends_on`：本事项需要目标已经交付的成果；
- `follows_up`：本事项在目标之后继续或改进；
- `supersedes`：本事项方向或方案替代目标旧方向。

每条关系必须有项目针对性理由。关系只用于追溯，不继承测试，不自动阻塞、排期、加锁、合并或解决冲突。
