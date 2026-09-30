已读取 [AGENTS.md](file:///D:/AboutDEV/Strixnova/.artifacts/validation/d8a2eeaa19bd/work/project/AGENTS.md)、[SKILL.md](file:///D:/AboutDEV/Strixnova/.artifacts/validation/d8a2eeaa19bd/work/project/.agents/skills/strixnova/SKILL.md) 以及 [direction-candidate.json](file:///D:/AboutDEV/Strixnova/.artifacts/validation/d8a2eeaa19bd/work/project/direction-candidate.json)。

以下是当前待决定的完整业务与工程方向候选说明：

---

### 方向候选概述

- **事项编号 / 状态**：`WI-20260928-9CA7291C`（状态：`awaiting_direction_confirmation`）
- **核心目标 (Goal)**：修复预约区间在结束刻度不大于开始刻度时的校验缺陷，抛出 `ValueError`。
- **排除目标 (Non-goals)**：不引入日期、时区或日历解释，不添加持久化或远程调用服务。

---

### 详细内容

#### 1. 范围与需求 (Scope & Requirements)
- **DIRREQ-A1B2C3D4E5F60718**：当结束刻度不大于开始刻度时（即 `end <= start`），抛出 `ValueError`。
- **DIRREQ-B2C3D4E5F6071829**：合法区间保持原有返回值（即 `end - start`），且函数签名与类型注解严格保持不变。

#### 2. 工程约束 (Constraints)
- **DIRCON-C3D4E5F60718293A**：严格保持 `duration(start: int, end: int) -> int` 函数签名与类型注解不变。

#### 3. 验收标准与行为用例 (Acceptance & Examples)
- **验收陈述 (DIRACC-D4E5F60718293A4B)**：结束刻度小于或等于开始刻度时抛出 `ValueError`，合法区间返回 `end - start`。
- **行为用例**：
  1. **合法区间保持原有时长**：`start=10`, `end=60` 时调用 `duration(10, 60)`，返回 `50`。
  2. **结束刻度等于开始刻度**：`start=30`, `end=30` 时调用 `duration(30, 30)`，抛出 `ValueError`。
  3. **结束刻度小于开始刻度**：`start=50`, `end=20` 时调用 `duration(50, 20)`，抛出 `ValueError`。

---

### 当前状态说明与等待

依据定点复验规则，第一段仅负责展示并向负责人说明候选内容，不修改任何文件，不代签决定，不调用 CLI 进行确认。

请审查上述方向内容并告知您的决定（如：是否接受该方向或有其他具体要求），我将等待您的明确答复。
