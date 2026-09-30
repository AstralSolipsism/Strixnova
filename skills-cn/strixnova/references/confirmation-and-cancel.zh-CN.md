# 确认与取消（中文审阅映射）

## 用户确认

在每个普通关口解释完整候选：推荐变化及其效果、当前事实、工程依据、重要取舍、风险、未知和授权范围。按候选组织内容，不套固定标题；会改变决定的信息须在询问前可见。解释 EngineeringPlan 或 ActualResult 时遵循 [cross-artifact-review.md](cross-artifact-review.zh-CN.md)。

包括小修复在内，这些说明必须在第一次请求接受之前完成。目标、范围、约束和预期例子的清单只是候选内容，不能代替决定说明。对照当前可观察结果与拟议结果，把差异与用户需要联系起来，并解释重要取舍及其后果。会改变决定的未知须如实说明；没有已知的此类未知时简要说明，不编造风险。不要等用户表示没看懂后才补上对比和理由。

用户要求详细解释时，展开同一候选，复用仍有效的决定，不增加“是否已经理解说明”的额外确认。

三个普通关口的授权范围保持独立：

- 方向：授权继续调查和形成工程方案，不授权源码、Git 交付、推送、发布或部署。
- 工程方案：授权本地实施与验证，不接受后续实际结果，也不授权 Git 交付、推送、发布或部署。
- 实际结果：接受已展示的实施与验证事实并授权本地 Git 交付，不授权远程推送、发布或部署；可以机械采用精确 ImplementationAlignment，不代替 ProductDefinition、DomainModel、TargetArchitecture、EngineeringPolicy 的独立接受。

用一句自然问题询问是否接受已展示候选，允许用户用自己的话回答，不要求口令或退回前缀。Agent 根据完整展示与后续答复记录 `agent_decision`：`decision` 为 `accept` 或 `request_changes`，`reason` 解释该答复如何适用于当前候选。这些字段以及 `decision_label`、`candidate_fingerprint`、schema 名和卡片编号都是内部信息，不要求用户填写。

用户没看懂或继续提问时，重新解释同一候选，不调用 `confirm`，不改变 WorkItem 版本或确认绑定。只有实质改变候选的纠正才按退回进入修订。“认同，执行”可以接受刚刚完整展示的候选；“可以，但先改范围”不能接受原候选。有明确纠正时记录 `request_changes`，条件或指向不清时只澄清该不确定处，不提交决定。不能仅因措辞或标点不同要求再答一次。

更早对澄清、推荐或取舍的回答，不是对后来形成的完整候选的确认。形成、提交或展示候选的同一轮不得调用 `confirm`。只有用户后续接受或退回该精确候选后，才按 [prepared-input.md](prepared-input.zh-CN.md) 传入已有原始消息来源和 Agent 判断；程序带入同一准备动作的指纹并原样保全消息。程序只检查身份、版本、状态和结构，不判断用户意图、解释质量、用户理解或候选语义。不能把不确定解释为接受。

下面是内部输入，不向用户展示：

```json
{
  "candidate_fingerprint": "sha256:...",
  "user_confirmation": "the user's exact later reply",
  "agent_decision": {
    "decision": "accept",
    "reason": "The later reply explicitly accepts the complete candidate just displayed."
  }
}
```

准备接口机械传递指纹及完整原话，包括空白、换行、标点和附带条件。不能让模型撰写所谓原文文件来模拟宿主输入；CLI 不能自行读取聊天消息。不制造或正规化原话，也不把旧答复作为其他关口或已改变候选的新决定；同一完整权威包内逐项携带同一答复遵循下方规则。关口由当前动作决定，早前决定不代表接受新候选。

## 长期权威候选

不得手工把上游候选设为 `confirmed`。按 CurrentAction 依赖顺序记录候选展示、提交绑定五类内容散列的八视角复核，再解释完整确认包。这与普通三个关口分开。负责人可以在一条后续消息中逐类决定，或明确接受整个展示包；每类接受范围仍须独立判断。缺项或指向不清时，先解决再提交。

通过准备接口一次提交各类 `agent_decision`；程序生成有序 `decisions` 数组并带入固定种类与指纹。同一消息明确覆盖整包时，原始来源只提供一次，由程序保留到各项，并分别保留 Agent 对适用范围的解释；不能截取同意片段而丢掉条件或纠正。

程序原子复核整包、写确认元数据和确认后散列。`authority_candidate_snapshot` 与 `accepted_candidate_snapshot_verified` 只证明接受后的正文未被替换，本地 Git 合入时还会复核真实提交；不证明语义正确。ImplementationAlignment 机械定档属于 ApplicationCoordinator 经公开 `delivery` 入口执行，Agent 不手改状态、负责人、日期或基线引用。

## 开始取消

```json
{"reason":"the user's actual reason"}
```

Strixnova 读取本地 Git 判断是否仍有工作。干净空工作可安全移除；未合入工作必须暂停等待用户决定。

## 决定遗留工作

向用户展示三种真实选择：保留原处、转移归属/位置、丢弃。然后提交之一：

```json
{"decision":"preserve","details":{}}
```

```json
{"decision":"transfer","details":{"destination":"..."}}
```

```json
{
  "decision":"discard",
  "details":{"reason":"..."},
  "confirm_discard":true
}
```

丢弃是破坏性操作，必须有用户明确确认；不能因为 Agent 推荐删除就设置 `confirm_discard`。


遇到 `resume_external_effect` 时，按[恢复已记录副作用](replanning.zh-CN.md#恢复已记录副作用)沿用原取消意图与已记录决定。
