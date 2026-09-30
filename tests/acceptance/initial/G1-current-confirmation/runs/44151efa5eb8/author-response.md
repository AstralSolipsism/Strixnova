已完成对当前工程上下文与需求规范的核验，并在治理框架中提交了方向候选（当前工作项处于等待负责人确认方向状态）。

### 业务背景与改动对比

- **当前现状**：`src.py` 中的 [`duration(start, end)`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/5cce0a8e359b/work/project/src.py#L1-L3) 仅执行 `return end - start`。当传入结束刻度不大于开始刻度（如 `start == end` 或 `end < start`）时，仍会返回 `0` 或负整数时长，无法拦截非法预约区间。
- **拟定方案**：
  - 在 [`duration`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/5cce0a8e359b/work/project/src.py#L1-L3) 内部增加刻度校验：若 `end <= start`，抛出 `ValueError`。
  - 保留原有函数签名 `duration(start: int, end: int) -> int` 不变。
  - 对于合法的 `end > start` 区间，保持原有时长计算 `end - start` 返回值不变。

### 方向候选明细

1. **目标（Goal）**：修复预约区间函数在结束刻度不大于开始刻度时的校验。
2. **范围（Scope）**：
   - 结束刻度 `end <= start` 时明确抛出 `ValueError`。
   - `end > start` 时保持返回 `end - start`，签名不变。
3. **非目标（Non-Goals）**：不引入日期/时间对象解析、不增加时区处理、不变更现有参数类型与接口结构。
4. **约束（Constraints）**：维持原有函数签名 `duration(start: int, end: int) -> int` 与合法区间的返回值。
5. **行为示例与验收（Acceptance Examples）**：
   - `duration(10, 10)` -> 抛出 `ValueError`
   - `duration(20, 10)` -> 抛出 `ValueError`
   - `duration(10, 60)` -> 正常返回 `50`
6. **决策边界**：本阶段仅确认建设方向，确认后将继续推进工程评估与工程方案制定，尚不执行代码改动或提交。

---

请问您是否同意并接受上述业务方向候选？
