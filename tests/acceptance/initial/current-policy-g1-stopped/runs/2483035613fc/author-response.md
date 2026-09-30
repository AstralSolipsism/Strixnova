### 工程方案候选确认

针对预约区间函数非法区间校验的修复，已完成工程评估并生成完整工程方案候选：

#### 1. 决策支持与变更概要
* **当前问题**：[`src.py`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/0de0760860ac/work/project/src.py) 中的 [`duration`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/0de0760860ac/work/project/src.py#L1-L3) 函数在结束刻度不大于开始刻度（$end \le start$）时未拦截，导致相等刻度返回 `0`、倒序刻度返回负数。
* **为什么重要**：预约区间必须具备严格正向时间跨度，未拦截会导致下游业务逻辑产生无效或异常预约数据。
* **推荐方案**：在 `duration` 中增加 `end <= start` 判断并抛出 `ValueError`，保持原有合法入参行为和函数签名不变；更新测试用例并同步刷新实现对齐底账。
* **替代选择**：保持现状不拦截（缺陷依然存在）或静默返回 0/负数（违反需求与领域不变量）。
* **下一步**：方案确认后进入实施切片，执行代码与测试变更、刷新实现对齐底账并运行 pytest 验证。

#### 2. 工程上下文与计划切片
* **实施切片（SLICE-001）**：
  * **代码修改**：在 [`src.py`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/0de0760860ac/work/project/src.py) 中增加异常校验，在 [`tests/test_duration.py`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/0de0760860ac/work/project/tests/test_duration.py) 中增加相等与倒序用例。
  * **实现对齐刷新**：通过 Strixnova 实现对齐工作流更新 [`docs/engineering/alignment.yaml`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/0de0760860ac/work/project/docs/engineering/alignment.yaml) 及相关底账。
  * **自动化验证**：调用 pytest 执行 `tests/test_duration.py`，完整覆盖方向中约定的 3 个行为示例（相等、倒序、合法）。
  * **人工审查**：核验函数签名 `duration(start: int, end: int) -> int` 保持不变。
* **风险与未知**：变更范围局限在单一纯函数及其测试与对齐底账，无跨模块或未知风险。
* **授权边界**：确认本工程方案仅授权在本地工作区执行上述切片的实施与测试验证，不代表代码已最终接受或提交。

请问是否接受当前展示的工程方案候选？
