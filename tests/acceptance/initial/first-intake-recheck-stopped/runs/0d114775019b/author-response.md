我先读取三份指定文件。
三份文件已读取。接下来查看当前项目状态，以了解已有工程的 confirmed 权威和上下文。
项目状态是 `unadopted_project`，尚无 confirmed 长期权威、无活动 WorkItem。接下来查看现有源码结构和 `request_projection.py`，理解已有组件的范围。
现在也查看已有的产品定义和领域模型，了解 confirmed 权威中的现状。
已完成全部必要调查。现在整理所获事实和关键缺口。

---

## 调查摘要

### 已有工程现状

| 维度 | 现状 |
|---|---|
| 项目权威 | `unadopted_project` — 产品定义和领域模型已 confirmed，但尚未完成 `create_project` 建立完整项目权威 |
| 已有功能 | [src.py](file:///D:/AboutDEV/Strixnova/.artifacts/validation/ce4d860dd4e3/work/project/src.py)：纯函数 `duration(start, end)`，整数分钟区间校验 |
| 产品范围 | [definition.yaml](file:///D:/AboutDEV/Strixnova/.artifacts/validation/ce4d860dd4e3/work/project/docs/product/definition.yaml)：仅含一个 Capability「预约区间校验」，non-goal 明确排除界面、持久化、远程服务 |
| 领域模型 | [core.yaml](file:///D:/AboutDEV/Strixnova/.artifacts/validation/ce4d860dd4e3/work/project/docs/domain/sources/core.yaml)：bounded_context 仅覆盖区间顺序校验，不保存预约 |
| 待审样本 | [request_projection.py](file:///D:/AboutDEV/Strixnova/.artifacts/validation/ce4d860dd4e3/work/project/.agent-inputs/g4-fixed/request_projection.py)：把所有申请显示为"已生效预约" — **不是验收过的实现**，不构成领域权威 |

### 你的请求涉及两个新能力

1. **成员取消自己的申请** — 属于成员服务
2. **负责人下载每周汇总** — 属于运营汇总

这两项均超出当前 confirmed 产品范围，属于新产品扩展。可以分别交付。

---

## 需要你明确的关键事实

在进入 WorkItem 登记之前，以下三个事实存在 [background.md](file:///D:/AboutDEV/Strixnova/.artifacts/validation/ce4d860dd4e3/work/project/.agent-inputs/g4-fixed/background.md) 记录的冲突或空白，我无法自行推断，需要你作为负责人提供：

### 问题 1：「申请」的业务含义

background.md 记录了两个口头说明存在冲突：
- 成员服务方说"成员可取消**自己的申请**"
- 运营方说"审批决定的结果不得由成员直接改写"

> **你需要明确：** 在本工程中，「申请」是指**尚未通过审批的待审核预约请求**，还是**已经审批生效的预约**，还是两者都有但处于不同生命周期阶段？成员"取消自己的申请"作用于哪个阶段？

### 问题 2：取消的业务边界

- 如果已审批生效的预约不允许成员直接取消（运营方立场），那成员能取消的**仅限于**待审核状态的申请吗？
- 还是存在第三种情况——例如生效预约也可由成员发起取消请求，但需要另一方审批？

> **你需要明确：** 取消操作的前置条件和对已审批结果的约束。

### 问题 3：「每周汇总」的输出范围

"负责人下载每周汇总"中：
- 汇总的内容是**所有申请**（含待审核、已生效、已取消）还是仅覆盖特定状态？
- 汇总的时间口径是自然周（周一至周日）还是其他起止？
- 输出格式有要求吗（例如 CSV、JSON、特定字段）？

> **你需要明确：** 汇总覆盖的申请状态、时间周期定义和输出格式要求。

---

请提供上述三个问题的实质决定，我将据此形成两个可分别交付的 WorkItem。在你回答之前我不会登记事项、修改代码或确认任何候选。
