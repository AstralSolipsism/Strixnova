# 输入准备与选定材料（中文审阅映射）

这些产品接口传递机械字段，不选择语义结果、不授予权限，也不代替阅读实际实现。
Python 接口为 `LocalHostAdapter.prepare_input`、`preview_input`、`apply_input`；
调用方可直接保存返回的上下文对象，无须处理 Shell JSON。

示例从管理项目根运行，传输材料写入被忽略的 `.strixnova/artifacts/agent-inputs/`，避免成为计划外源码变化。程序创建必要父目录，但不会覆盖已有文件；新一轮使用新文件名。也可指定项目外的普通临时目录。

## 准备一次，只提交判断

```text
strixnova action prepare --work-item-id <ID> --output .strixnova/artifacts/agent-inputs/action-context.json
strixnova action inspect --source .strixnova/artifacts/agent-inputs/action-context.json --pointer /checklist --readable
strixnova action preview --context .strixnova/artifacts/agent-inputs/action-context.json --input @.strixnova/artifacts/agent-inputs/answers.json --output .strixnova/artifacts/agent-inputs/input-preview.json
strixnova action apply --context .strixnova/artifacts/agent-inputs/action-context.json --input @.strixnova/artifacts/agent-inputs/answers.json
```

程序固定精确动作、事项版本、确认指纹和必要身份。读取准备包中的合同与清单，只提交
根级 `fields` 和逐项 `answers`，不要把完整模板再抄回来。程序沿用既有命令路由和校验。
写后复用返回的 `next`。遇到 `prepared_input_stale` 须重新准备并审阅，不能把旧判断
换绑到新身份。准备包是可丢弃的传输快照，不是第二份权威、批准回执或实际阅读证明。

ActualResult 每行清单给出固定身份、来源、输入 Schema 和待填字段。缺失判断保持缺失。
效果、结果、状态、理由、证据、偏差与限制均由 Agent 明确给出。相同判断可用 `groups`，
其中 `items` 明列清单 ID，`values` 给出共享判断；程序只展开指定项。不得把漏项自动填成
`realized`、`satisfied` 或 `supported`。

从 `evidence_catalog` 选择结果证据，或使用类型化引用，如
`{"kind":"receipt","key":"VR-..."}`、`{"kind":"delivered_outcomes","key":0}`。
程序转成正式引用字符串。计划阶段的 `direction`、`SRC-*` 不会自动成为实际结果证据。
可引用及身份匹配不等于证据支撑了结论。

`preview` 是可选只读预检，报告独立的结构错误和不可用结果引用；结构完整的结果继续
使用正式提交中的同一结果检查。它不证明语义正确，也不保证稍后可写入；apply 仍核对
当前性以及原有副作用和授权门槛。解释 `ok` 前须读取完整预检报告，它不是负责人接受。

## 用户消息与确认

调用方已取得原始消息时，通过 Python API 的 `user_message` 直接传入。已有用户或宿主
提供的原文文件时，为 `action preview` 和 `action apply` 添加 `--user-message-file`；
`confirm`、`authority` 也支持该参数。另行明确提交 `agent_decision`。同一消息可由程序
展开到完整权威决定包，每类仍须有独立的范围解释和决定。

保留空白、换行、标点和条件。不要让模型撰写所谓“原文文件”、用摘要代替原文，或把任意
文件标成已认证的负责人输入。CLI 无法自行取得聊天消息。没有可用原文来源时，如实报告
宿主限制；这不允许推导同意。原有后续消息、精确候选及负责人解释要求继续适用。

## 读取选定范围，无须搬运游标

```text
strixnova action records --work-item-id <ID> --record engineering.plan --record engineering.execution_context --output .strixnova/artifacts/agent-inputs/selected-material.json
strixnova action inspect --source .strixnova/artifacts/agent-inputs/selected-material.json --pointer /records --readable
```

按当前问题选择允许读取的引用。程序只汇集这些引用，重查版本与字节，再保存 UTF-8 材料，
不往会话里倾倒所有上下文。检查输出有界，并明确 `unexpanded` 指针。`complete=false`
表示显示仍省略正文；从已保存材料读取必要正文，不能把索引或宿主截断视图当成完整上下文。
ASCII 机器传输及规范散列算法保持不变。

## 批量展示与明确修订

已编写且已获准处理的候选都准备好后，可使用 `action authorities`，传入固定 `--context`
及明确有序的重复 `--kind`。程序保留逐类展示事件和版本；候选缺失、需要复核或需要负责人
决定时停止，并报告已完成前缀。继续前先读该报告；登记不表示负责人已经看见或理解。

修订方向或工程评估时，先读 `revision_bases`，再提交 `revision`：明确 `kind`、
`keep_rest: true`，并用 JSON 指针 `changes` 执行 `add`、`replace`、`remove`。
“其余保持适用”是 Agent 的明确判断。程序保留精确底稿、递增评估修订号、带入当前已接受
方向绑定，生成完整候选后仍走正常校验与重新确认，不继承旧接受。机械 YAML 元数据更新
继续由既有实现对齐准备与写入入口负责；不得手工修改确认元数据。

`alignment prepare --output .strixnova/artifacts/agent-inputs/alignment-context.json` 保存绑定。使用
`alignment inspect --prepared .strixnova/artifacts/agent-inputs/alignment-context.json`、
`alignment write-candidate --prepared .strixnova/artifacts/agent-inputs/alignment-context.json --input @.strixnova/artifacts/agent-inputs/decisions.json`，
无须复制 `preparation_ref`、事项 ID 或版本。外部捕获仍须 `--authorize-external`；用它的
`--output` 保存更新后的上下文。不能拿最新引用套用对旧内容的决定。

## 验证事实与精确测试身份

在 `assess_verification_change` 阶段，用 `--receipt-id` 选择当前列出的待判断回执。程序
带入命令与回执身份，提供 `verification_observations`：已捕获范围内的变化、未变化、未
捕获路径，执行期间变化，已记录限制和依赖证据。范围外仍未知。相关性、断言充分性、外部
依赖影响与重测必要性必须明确判断；退出码为零或已捕获字节相同不能自动给出
`needs_retest: false`。

用 `action cases --context .strixnova/artifacts/agent-inputs/action-context.json --command-id <ID> --report .strixnova/artifacts/agent-inputs/collection.json --output .strixnova/artifacts/agent-inputs/case-preflight.json`
检查已有测试报告，同时核对测试根与精确收集到的 node ID。失配逐项报告，不模糊替换，
不修改已批准命令。这里不执行收集。没有报告时，pytest 收集会执行代码，须先取得单独
明确执行授权。调用方提供的报告只是准备材料，不是已验证执行回执，也不证明断言符合
预期行为。

使用 `alignment inspect --prepared .strixnova/artifacts/agent-inputs/alignment-context.json --output .strixnova/artifacts/agent-inputs/alignment-material.json` 自动汇集所选准备包，无须搬运游标；用 `action inspect` 查看保存的 `/items`。汇集不证明已完成审阅。
