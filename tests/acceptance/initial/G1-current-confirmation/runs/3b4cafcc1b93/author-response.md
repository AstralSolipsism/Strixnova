好的，我们通过**修改前后的直观行为对比**来更清晰地说明本次修改内容：

---

### 修改前后的行为差异对比

| 调用场景 | 传入参数 | 修改前（当前实际表现） | 修改后（拟定目标表现） | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| **结束等于开始** | `duration(10, 10)` | 返回 `0` | **抛出 `ValueError`** | 零时长不是合法预约区间，予以拦截 |
| **结束早于开始** | `duration(20, 10)` | 返回 `-10` | **抛出 `ValueError`** | 逆序刻度非法，予以拦截 |
| **合法正常区间** | `duration(10, 60)` | 返回 `50` | 返回 `50` | 正常合法区间，保持原样无影响 |

---

### 代码层面的具体变化

- **修改前代码**（[`src.py`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/5cce0a8e359b/work/project/src.py#L1-L3)）：
  ```python
  def duration(start: int, end: int) -> int:
      """Return the duration between integer minute marks."""
      return end - start
  ```
  直接相减，未对参数顺序进行合法性判定。

- **修改后代码**：
  ```python
  def duration(start: int, end: int) -> int:
      """Return the duration between integer minute marks."""
      if end <= start:
          raise ValueError("end must be greater than start")
      return end - start
  ```
  在计算前新增检查：只要 `end <= start`，立即抛出 `ValueError`；只有当 `end > start` 时才执行减法返回时长。函数名称、参数与返回值类型完全保持不变。

---

本次方向确认旨在确认：**当且仅当 `end <= start` 时拒绝并抛出 `ValueError`，合法输入继续计算时长，函数签名完全不变**。

请问您对这一方向候选是否认可并同意继续推进方案制定？
