### 方向决策确认

针对您提出的预约区间函数缺陷，已形成完整方向决策候选：

* **目标与背景**：当前 [`duration`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/0de0760860ac/work/project/src.py#L1-L3) 函数直接执行 `end - start`，在结束刻度不大于开始刻度时（如相等或倒序）未做拦截。本次修复将在结束刻度不大于开始刻度时抛出 `ValueError`，同时保持函数签名与合法区间的计算行为完全不变。
* **范围与需求**：
  * 当 $end \le start$ 时抛出 `ValueError`。
  * 当 $end > start$ 时保持返回值 `end - start`。
  * 保持函数签名 `duration(start: int, end: int) -> int` 不变。
* **验收行为示例**：
  1. `duration(10, 10)` $\rightarrow$ 抛出 `ValueError`
  2. `duration(20, 10)` $\rightarrow$ 抛出 `ValueError`
  3. `duration(10, 60)` $\rightarrow$ 正常返回 `50`
* **权衡与风险**：仅修复未校验非法区间的缺陷，不存在跨模块影响或已知风险。
* **授权边界**：确认本方向仅授权继续进行工程评估与计划编制，不代表代码已变更或交付。

请问是否接受当前展示的方向候选？
