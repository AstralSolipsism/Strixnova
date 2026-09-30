### 修改前后的行为与代码差异对比

针对 [`src.py`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/0de0760860ac/work/project/src.py) 中的 [`duration`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/0de0760860ac/work/project/src.py#L1-L3) 函数，本次修改前后的核心差异如下：

#### 1. 行为差异对比

| 调用场景 | 输入示例 | 当前行为（修改前） | 修复后行为（修改后） | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| **合法区间** ($end > start$) | `duration(10, 60)` | 返回 `50` | 返回 `50` | 保持原有逻辑与返回值不变 |
| **刻度相等** ($end == start$) | `duration(10, 10)` | 返回 `0`（未拦截） | **抛出 `ValueError`** | 预约区间无效，明确拦截 |
| **倒序刻度** ($end < start$) | `duration(20, 10)` | 返回 `-10`（负数时长） | **抛出 `ValueError`** | 结束时间早于开始时间，明确拦截 |

#### 2. 代码实现对比

* **修改前**：
  ```python
  def duration(start: int, end: int) -> int:
      """Return the duration between integer minute marks."""
      return end - start
  ```
* **修改后**：
  ```python
  def duration(start: int, end: int) -> int:
      """Return the duration between integer minute marks."""
      if end <= start:
          raise ValueError(f"end ({end}) must be greater than start ({start})")
      return end - start
  ```

#### 3. 授权边界与说明
当前步骤仍处于**方向确认**阶段：确认该方向仅授权继续进行工程评估与计划编制，不代表代码已变更或提交。

请问是否接受当前展示的方向候选？
