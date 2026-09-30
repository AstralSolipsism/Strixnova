已读取所有三份材料。按 AGENTS.md 规则，当前允许调查、登记和只读澄清。我先查看项目当前状态和已有代码，然后准备 intake。
现在对项目事实已有基本把握。项目处于 `unadopted_project` 状态，现有业务代码只有纯函数区间校验 ([src.py](file:///D:/AboutDEV/Strixnova/.artifacts/validation/bb12246aa8bc/work/project/src.py))，取消和周报都是新范围。你的请求是可识别的具体管理事项，我需要通过 `strixnova intake` 登记。

你提到这两个结果可以分别交付，所以我为每个登记一个独立的 WorkItem。先从"成员取消自己的申请"开始。
第一个 WorkItem `WI-20260929-9F34387C` 已创建，状态为 discussion，下一步是 submit_direction。继续创建第二个。
两个 WorkItem 已登记：
- **WI-20260929-9F34387C** — 成员取消自己的预约申请
- **WI-20260929-1A4B51B6** — 负责人下载每周汇总

两项下一步都是 `submit_direction`。在形成方向前，我需要读取 direction 参考、input contract 以及 `project.direction_context`，了解方向提交的格式要求。先从第一个 WorkItem 开始读取所需记录。
已读取方向参考和第一个 WorkItem 的记录。项目是 `unadopted_project`，所以 `context_ref: null`，capability 和 guardrail 为空列表。我还需要读取 input contract 的 `payload_schema` 和 `instructions` 来确保提交格式正确。

但更重要的是——在形成方向之前，我需要先解决 [background.md](file:///D:/AboutDEV/Strixnova/.artifacts/validation/bb12246aa8bc/work/project/.agent-inputs/g4-fixed/background.md) 中指出的业务含义冲突。这些是需要你（负责人）明确的关键事实。

---

## 已完成的登记

两个 WorkItem 已成功创建：

| WorkItem | 标题 | 状态 |
|---|---|---|
| `WI-20260929-9F34387C` | 成员取消自己的预约申请 | discussion → 待提交方向 |
| `WI-20260929-1A4B51B6` | 负责人下载每周汇总 | discussion → 待提交方向 |

## 需要你明确的关键事实

在形成任一事项的方向前，以下业务含义缺口必须由你决定，我无法从代码或已有材料推导：

### 问题 1：「申请」的状态边界

background.md 记录了冲突：成员服务方说"成员可取消自己的申请"，运营方说"审批决定的结果不得由成员直接改写"。

**具体问题：成员能取消的"申请"，是仅限尚未审批的待审核申请，还是也包括已审批生效的预约？**

- 如果仅限待审核：取消只撤回未决请求，已批准的预约不受影响。
- 如果也包括已生效：成员可以单方面撤销已批准的预约，这与运营方的约束直接冲突。

### 问题 2：「每周汇总」的内容范围

"负责人下载每周汇总"——汇总的对象是什么？

- 仅汇总预约申请（含各状态：待审核、已批准、已取消）？
- 还是汇总预约的实际使用/执行情况？
- "每周"的周期起止是自然周（周一到周日）还是其他定义？

### 问题 3：取消操作的效果

成员取消一个待审核申请后，该申请记录是被删除还是标记为"已取消"状态保留？这影响周报汇总是否包含被取消的申请。

---

请先回答问题 1，后续问题可以根据你的回答调整。
