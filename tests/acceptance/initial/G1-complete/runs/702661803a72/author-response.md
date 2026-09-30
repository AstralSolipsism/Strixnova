已完成工程评估与工程方案制定。到达需要负责人明确决定的**工程方案确认关口（Engineering Plan Confirmation）**，具体方案候选如下：

---

### 工程方案候选

#### 1. 决策支持（Owner View）
* **当前问题**：
  预约区间函数在结束刻度不大于开始刻度时（`end <= start`）仍直接相减返回结果，导致非法时间刻度被放行，违反了领域中“合法区间必须具有正时长”的业务不变量。
* **为什么重要**：
  若非法时间顺序进入后续排期流程，会产生负时长或零时长脏数据；需要在组件入口处建立防御。
* **影响范围**：
  仅修改 [src.py](file:///D:/AboutDEV/Strixnova/.artifacts/validation/f0addbc9966a/work/project/src.py) 中 `duration(start: int, end: int)` 的错误分支行为（`end <= start` 时抛出 `ValueError`），保持合法正区间（`end > start`）的计算与函数签名完全不变；同步补充测试断言与实现对齐底账记录。
* **推荐做法**：
  在 `duration` 入口增加校验 `if end <= start: raise ValueError(...)`，并在 [tests/test_duration.py](file:///D:/AboutDEV/Strixnova/.artifacts/validation/f0addbc9966a/work/project/tests/test_duration.py) 中增加对相等刻度和反序刻度的测试用例。
* **替代选择**：
  由外部调用方自行防御（不推荐，函数本身仍存在漏洞且违反领域不变量）。
* **不处理后果**：
  非法刻度继续被当作正常区间返回，导致后续业务产生脏数据。
* **下一步**：
  方案确认后，进入实施切片（执行代码修改、测试断言验证及实现对齐刷新）。

---

#### 2. 工程上下文与实施安排
* **实施切片（SLICE-001）**：
  1. 修改 [src.py](file:///D:/AboutDEV/Strixnova/.artifacts/validation/f0addbc9966a/work/project/src.py)：增加非法刻度校验。
  2. 修改 [tests/test_duration.py](file:///D:/AboutDEV/Strixnova/.artifacts/validation/f0addbc9966a/work/project/tests/test_duration.py)：补充相等刻度与反序刻度抛出 `ValueError` 的 pytest 断言。
  3. 刷新实现对齐底账：更新 [docs/engineering/alignment.yaml](file:///D:/AboutDEV/Strixnova/.artifacts/validation/f0addbc9966a/work/project/docs/engineering/alignment.yaml) 及关联底账，记录修复后的源码观察和完全实现的模块职责。
* **验证计划**：
  使用虚拟环境解释器执行命令：
  `D:\AboutDEV\Strixnova\.venv\Scripts\python.exe -m pytest tests/test_duration.py -q`
  逐项核验并生成报告覆盖以下目标：
  * `DIREX-E5F60718293A4B5C`（合法区间返回正时长）
  * `DIREX-F60718293A4B5C6D`（相等刻度抛出 `ValueError`）
  * `DIREX-0718293A4B5C6D7E`（反序刻度抛出 `ValueError`）
  * `DIRCON-C3D4E5F60718293A`（函数签名保持不变）

---

#### 3. 授权边界
本关口确认仅授权在本地按上述方案实施修改与验证，不代表实际结果（Actual Result）的最终验收，亦不包含远程 Git 操作。

---

请确认是否接受上述工程方案？（您可以直接回复同意/批准，或提出需要调整的意见）
