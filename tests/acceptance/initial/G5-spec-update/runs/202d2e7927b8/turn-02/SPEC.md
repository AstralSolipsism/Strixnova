# 工程规格书：修复预约区间结束不大于开始的校验缺陷及单次区间上限规则（候选）

> **文档性质与定位**：本文件为根据建设事项历史记录及最新输入投影生成的可阅读工程规格（Reading View / SPEC）。
> **唯一权威声明**：已记录的建设事项历史与既有长期权威为各自唯一事实与决策来源。本文档作为可读投影，**不构成第二份权威**，不替代原决策确认，亦不因格式化阅读视图而改写任何既有事实。

---

## 1. 规格来源与稳定身份绑定 (Specification Basis & Identity Bindings)

本工程规格明确区分**既有已确认基线**与**当前未接受的方向候选**，严格绑定各自来源、版本与确认状态：

- **所属建设事项**：
  - 事项标识 (`work_item_id`): `WI-20260928-9CA7291C`
  - 事项标题: 修复预约区间结束不大于开始的校验缺陷
  - 事项状态 (`status`): `completed`（既有基线事项历史记录的事实状态；事项已执行进度仅作为历史事实，不替代规格含义或原确认）
  - 来源文档夹具: [`inputs/source-view.json`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/202d2e7927b8/work/project/inputs/source-view.json)（合成未接受方向修订 `synthetic_unaccepted_direction_revision`，总版本 `aggregate_version: 21`）及基线记录 [`inputs/recorded-work-item.json`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/202d2e7927b8/work/project/inputs/recorded-work-item.json)
- **方向决策绑定 (Direction Decision Bindings)**：
  - **既有已确认基线 (Accepted Baseline)**：
    - 方向版本: `direction_version: 3`
    - 候选指纹: `sha256:f5a2afd114a4ad47b16a8406f8e78c0fa1c4fbb5a5d4905bc7317873d3e8b06a`
    - 负责人确认状态: `accepted`（已于 2026-09-28T07:30:10.513746Z 确认方向）
    - 范围界定: 仅定义预约区间结束刻度不大于开始刻度时抛出 `ValueError`，合法正区间保持原有时长。
  - **当前未接受候选 (Current Unaccepted Candidate)**：
    - 方向版本: `direction_version: 4`
    - 候选状态 (`candidate_status`): `draft`（草案，**未被负责人接受**，`owner_accepted_by_this_input: false`）
    - 语义源变动: `semantic_sources_changed: true`（方向决策正文发生实质语义变动）
    - 范围变动: 在保留既有顺序校验与函数签名的前提下，引入单次正区间长度不超过 480 分钟的候选规则。
- **工程评估与方案绑定及处置 (Engineering Assessment & Plan Disposition)**：
  - 评估标识 (`assessment_id`): `EA-20260928-11111111`（修订 `assessment_revision: 1`）
  - 原方案标识 (`plan_id`): `PLAN-EA-20260928-11111111-R1`
  - 原方案确认状态: `accepted`（针对方向第 3 版的实现方案，指纹 `sha256:3e50e03c1a956e1cb89ee7abc6d0f4475d603c367ff6cc9aa3b8cf5b7db82e64`）
  - **旧方案处置与缺口声明 (Plan Disposition & Gaps)**：
    - **处置说明**：原工程方案系针对已确认方向第 3 版制定，**尚未为新上限规则重评**。
    - **主要缺口**：新候选规则（单次正区间不超过 480 分钟）的代码实现操作、测试覆盖断言、实现对齐刷新以及负责人方案确认均处于**待完成 (Pending)** 状态。本规格不得将原方案当作已支持上限规则的有效方案。
  - 治理基线与保障等级: `A1`，治理剖面 `strixnova-general-software-engineering+POLICY-1111111111111111`
- **上游权威基线绑定 (Upstream Authority Baselines)**：
  - 产品定义: `PRODUCT-1111111111111111` (`docs/product/definition.yaml`, `REVISION-1111111111111111`)
  - 领域模型: `MODEL-1111111111111111` (`docs/domain/model.yaml`, `MODELREV-1111111111111111`)
  - 目标架构: `ARCH-1111111111111111` (`docs/architecture/model.yaml`, `ARCHREV-1111111111111111`)
  - 实现对齐: `ALIGNMODEL-1111111111111111` (`docs/engineering/alignment.yaml`, `ALIGNREV-1111111111111111`)

---

## 2. 变更背景与目标定义 (Purpose, Problem & Scope)

### 2.1 变更背景与核心问题
预约区间计算函数原实现未对非法反序或零时长区间（$end \le start$）做有效拦截。在完成修复反序校验缺陷的基础上，业务方提出关于业务时长边界控制的新候选诉求：防止单次预约时长过长（例如超过 8 小时 / 480 分钟），需对合法正区间的长度施加上限约束。

### 2.2 建设目标 (Goal)
- **既有基线目标**：修复预约区间在结束刻度不大于开始刻度时的校验缺陷，抛出 `ValueError`；保持函数签名与类型注解不变。
- **当前候选目标**：在保留既有区间顺序校验与函数签名的前提下，增加单次区间不超过 480 分钟的候选规则（正区间大于 480 分钟抛出 `ValueError`，恰好 480 分钟仍接受并返回时长数值）。

### 2.3 明确非目标 (Non-Goals)
- 不引入日期、时区或日历解释逻辑。
- 不添加数据持久化层或远程调用服务。
- 不扩展或更改除预约区间时长纯函数以外的其他模块。

---

## 3. 行为契约与需求规范 (Behavioral Contract & Requirements)

本节精确映射并保留方向中的稳定需求与约束标识，区分既有稳定条目与当前未接受候选新增/调整的条目：

### 3.1 需求条目 (Direction Requirements)

- **`DIRREQ-A1B2C3D4E5F60718`（既有稳定保留）**：
  - **状态**: 既有已确认需求，不受本次候选影响。
  - **行为定义**：当预约区间的结束刻度不大于开始刻度时（即数学关系满足 $end \le start$），系统必须拒绝该调用并立即抛出标准异常 `ValueError`。
  - **触发条件**：调用预约区间时长计算函数，传入参数满足 $end \le start$（包含结束等于开始的零时长情况，以及结束小于开始的反序情况）。
  - **可观察结果**：抛出 `ValueError` 异常，不产生有效返回值，不产生副作用。

- **`DIRREQ-B2C3D4E5F6071829`（范围修订候选，未接受）**：
  - **状态**: 候选修订（未接受）。在既有规则基础上增加了不超过 480 分钟的条件限制。
  - **行为定义**：合法区间长度不超过 480 分钟时仍返回 $end - start$，函数签名不变。
  - **触发条件**：调用预约区间时长计算函数，传入参数满足 $0 < end - start \le 480$。
  - **可观察结果**：计算并返回正确的整数时长数值（等于 $end - start$）。

- **`DIRREQ-18293A4B5C6D7E8F`（新规候选条目，未接受）**：
  - **状态**: 新增候选需求（未接受，草案状态）。
  - **行为定义**：正区间长度大于 480 分钟时抛出 `ValueError`；恰好 480 分钟仍接受。
  - **触发条件**：调用预约区间时长计算函数，传入参数满足 $end - start > 480$。
  - **可观察结果**：抛出 `ValueError` 异常，拒绝超长预约。

### 3.2 稳定设计约束 (Direction Constraints)

- **`DIRCON-C3D4E5F60718293A`（既有稳定保留）**：
  - **状态**: 既有已确认约束，不受本次候选影响。
  - **约束声明**：严格保持 `duration(start: int, end: int) -> int` 的函数名称、入参个数、入参类型注解及返回值类型注解完全一致，不得改变公共接口暴露形式。

---

## 4. 行为示例与验收准则 (Behavior Examples & Acceptance Criteria)

### 4.1 验收准则 (Acceptance Item)

- **`DIRACC-D4E5F60718293A4B`（准则陈述扩展候选，未接受）**：
  - **既有基线陈述**: 结束刻度小于或等于开始刻度时抛出 `ValueError`，合法区间返回 `end - start`。
  - **候选修订陈述**: 结束不晚于开始或正区间长度大于 480 分钟时抛出 `ValueError`；其余正区间返回 `end - start`。
  - **关联需求**: 覆盖 [`DIRREQ-A1B2C3D4E5F60718`](#31-需求条目-direction-requirements)、[`DIRREQ-B2C3D4E5F6071829`](#31-需求条目-direction-requirements) 及新增候选 [`DIRREQ-18293A4B5C6D7E8F`](#31-需求条目-direction-requirements)。
  - **适用性**: 必需 (`required`)。

### 4.2 权威行为示例 (Behavior Examples)

方向决策候选第 4 版共包含 5 组行为示例（保留 3 组既有示例，新增 2 组上限边界候选示例）：

#### 示例 1: 合法区间保持原有时长（既有保留）
- **示例标识**: `DIREX-E5F60718293A4B5C`
- **确认状态**: 既有已确认
- **溯源依据**: `DIRREQ-B2C3D4E5F6071829`
- **Given（前置条件）**: `start=10`, `end=60`
- **When（触发操作）**: 调用 `duration(10, 60)`
- **Then（预期结果）**: 返回 `50`

#### 示例 2: 结束刻度等于开始刻度时抛出 ValueError（既有保留）
- **示例标识**: `DIREX-F60718293A4B5C6D`
- **确认状态**: 既有已确认
- **溯源依据**: `DIRREQ-A1B2C3D4E5F60718`
- **Given（前置条件）**: `start=30`, `end=30`
- **When（触发操作）**: 调用 `duration(30, 30)`
- **Then（预期结果）**: 抛出 `ValueError`

#### 示例 3: 结束刻度小于开始刻度时抛出 ValueError（既有保留）
- **示例标识**: `DIREX-0718293A4B5C6D7E`
- **确认状态**: 既有已确认
- **溯源依据**: `DIRREQ-A1B2C3D4E5F60718`
- **Given（前置条件）**: `start=50`, `end=20`
- **When（触发操作）**: 调用 `duration(50, 20)`
- **Then（预期结果）**: 抛出 `ValueError`

#### 示例 4: 恰好上限仍接受（新增候选，未接受）
- **示例标识**: `DIREX-18293A4B5C6D7E8F`
- **确认状态**: 候选草案 (Draft)
- **溯源依据**: `DIRREQ-18293A4B5C6D7E8F`
- **Given（前置条件）**: `start=20`, `end=500` ($500 - 20 = 480$)
- **When（触发操作）**: 调用 `duration(20, 500)`
- **Then（预期结果）**: 返回 `480`

#### 示例 5: 超过上限拒绝（新增候选，未接受）
- **示例标识**: `DIREX-293A4B5C6D7E8F90`
- **确认状态**: 候选草案 (Draft)
- **溯源依据**: `DIRREQ-18293A4B5C6D7E8F`
- **Given（前置条件）**: `start=20`, `end=501` ($501 - 20 = 481$)
- **When（触发操作）**: 调用 `duration(20, 501)`
- **Then（预期结果）**: 抛出 `ValueError`

---

## 5. 工程实现方案现状与处置说明 (Engineering Design & Plan Disposition)

### 5.1 既有工程方案与当前处置
- **原方案标识**: `PLAN-EA-20260928-11111111-R1`
- **既有方案范围**: 仅包含应对 $end \le start$ 缺陷的代码修改 (`src.py`)、基础测试用例 (`tests/test_duration.py`) 以及实现对齐底账刷新（`operations[0]` 至 `operations[7]`）。
- **处置说明**:
  - 原工程方案系基于方向第 3 版制定并获得负责人确认。
  - **原方案尚未为 480 分钟上限规则进行工程重评 (Unreassessed for 480-minute limit)**。
  - 当前不得将既有方案视为已包含新上限规则的实施方案。

### 5.2 方案缺口与待决事项 (Engineering Gaps)
1. **代码设计与实现缺口**：`src.py` 中尚未规划或实现针对 $end - start > 480$ 的边界拦截逻辑。
2. **验证设计缺口**：既有验证命令 `VC-001` 的测试用例集合仅绑定了前 3 组示例，尚未规划覆盖 `DIREX-18293A4B5C6D7E8F`（恰好 480）和 `DIREX-293A4B5C6D7E8F90`（超过 480）的自动化测试断言。
3. **治理决策缺口**：方向第 4 版处于未接受的 `draft` 状态；若负责人后续接受该方向，必须通过 Strixnova 流程重新发起工程评估，制定修订版工程方案，并经过负责人的方案确认后方可进入代码修改与实施。

---

## 6. 验证安排现状与策略 (Verification Targets & Status)

### 6.1 既有验证命令 (Existing Verification Command)
- **命令标识**: `VC-001`
- **执行程序**: `D:\AboutDEV\Strixnova\.venv\Scripts\python.exe`
- **执行参数**: `-m pytest tests/test_duration.py -q`
- **已覆盖目标 (既有)**: `DIREX-E5F60718293A4B5C`, `DIREX-F60718293A4B5C6D`, `DIREX-0718293A4B5C6D7E`, `DIRCON-C3D4E5F60718293A`

### 6.2 候选示例的验证缺口声明
- 示例 `DIREX-18293A4B5C6D7E8F` 与 `DIREX-293A4B5C6D7E8F90` 属于方向第 4 版候选新增内容，**目前尚无已确认的验证命令、测试用例或执行回执与之绑定**。
- 不得虚构针对候选示例的已执行测试或通过证明。

---

## 7. 事项执行事实与已知限制 (Progress Facts & Known Limitations)

> **原则说明**：本节陈述的事项执行进度与回执数据仅作为工程历史进度的事实记录，**不替代上述规范含义或原确认**。

### 7.1 进度事实记录
- **历史验证回执**: `VR-WI-20260928-9CA7291C-F472B33294`（针对原方案实施的 `VC-001`，仅覆盖第 3 版方向需求，状态为 `passed`）。
- **历史实际结果确认**: 负责人曾于 2026-09-28T08:02:36.554746Z 确认方向第 3 版的实际结果。
- **历史代码提交与合入**:
  - 工作提交 (`result_commits`): `071b446e7658239d3b3081ac2b5ddbcf47f2eb15`
  - 集成合入 (`integrated_commit`): `30c96c7ea14df68b959043177eae03edba0f0a3a` (合入至 `main` 分支)
- **当前状态**: 本事项在真实历史中已完成第 3 版范围交付；当前方向第 4 版为最新输入的候选草案，尚无后续实施与合入。

### 7.2 真实限制记录 (Limitations)
- **新候选未接受**: 方向第 4 版（480 分钟上限）尚未经过负责人确认，其法律效力与工程授权等同于待审提案。
- **新方案未重评**: 当前工程代码库与测试库仍处于第 3 版交付后状态，不支持也不包含 480 分钟超长校验。
- **语义证明边界**: 所有语义内容与断言审阅均未声称机器严格证明 (`semantic_content_machine_proven: false`)。

---

## 8. 全要素覆盖索引 (Coverage Index)

本索引全面对照既有基线与未接受候选，核验本规格文档对所有稳定标识与操作要素的覆盖及处置情况：

| 要素类别 | 原始稳定标识 / 要素 | 状态属性 | 对应规格章节 | 覆盖与处置状态说明 |
|---|---|---|---|---|
| 方向需求 (Requirement) | `DIRREQ-A1B2C3D4E5F60718` | 既有已确认 | 3.1 节 | 完全覆盖 (Represented)，$end \le start$ 抛出 ValueError |
| 方向需求 (Requirement) | `DIRREQ-B2C3D4E5F6071829` | 候选修订 (Draft) | 3.1 节 | 完全覆盖 (Represented)，增补 $\le 480$ 分钟限制说明 |
| 方向需求 (Requirement) | `DIRREQ-18293A4B5C6D7E8F` | 候选新增 (Draft) | 3.1 节 | 完全覆盖 (Represented)，正区间 $> 480$ 抛出 ValueError 规则 |
| 方向约束 (Constraint) | `DIRCON-C3D4E5F60718293A` | 既有已确认 | 3.2 节 | 完全覆盖 (Represented)，约束保持 duration 签名与注解不变 |
| 方向验收 (Acceptance) | `DIRACC-D4E5F60718293A4B` | 候选扩展 (Draft) | 4.1 节 | 完全覆盖 (Represented)，纳入超长拦截综合验收陈述 |
| 行为示例 (Example) | `DIREX-E5F60718293A4B5C` | 既有已确认 | 4.2 节 | 完全覆盖 (Represented)，合法区间保持原有时长 (10, 60 -> 50) |
| 行为示例 (Example) | `DIREX-F60718293A4B5C6D` | 既有已确认 | 4.2 节 | 完全覆盖 (Represented)，相等刻度抛错 (30, 30 -> ValueError) |
| 行为示例 (Example) | `DIREX-0718293A4B5C6D7E` | 既有已确认 | 4.2 节 | 完全覆盖 (Represented)，反序刻度抛错 (50, 20 -> ValueError) |
| 行为示例 (Example) | `DIREX-18293A4B5C6D7E8F` | 候选新增 (Draft) | 4.2 节 | 完全覆盖 (Represented)，恰好上限接受 (20, 500 -> 480) |
| 行为示例 (Example) | `DIREX-293A4B5C6D7E8F90` | 候选新增 (Draft) | 4.2 节 | 完全覆盖 (Represented)，超过上限抛错 (20, 501 -> ValueError) |
| 历史工程操作 | `operations[0]` ~ `[7]` | 既有历史方案 | 5.1 节 | 完全处置 (Disposed)，标明仅对应原缺陷修复，未含新规则 |
| 方案重评缺口 | `PLAN-GAP-480MIN` | 待决缺口 (Gap) | 5.2 节 | 明确揭示 (Exposed)，新上限规则待重评方案、实现与测试 |
| 验证命令 (Command) | `VC-001` | 既有已确认 | 6.1 节 | 完全覆盖 (Represented)，标明仅覆盖既有 3 组示例与签名 |
| 验证缺口 (Command Gap) | `VERIFY-GAP-CANDIDATES` | 待决缺口 (Gap) | 6.2 节 | 明确揭示 (Exposed)，候选示例目前无绑定命令与测试断言 |
| 长期产物变更 | `ALIGNMODEL-1111111111111111` | 既有基线 | 1 节 | 维持引用 (Referenced)，既有对齐候选尚未包含新规则 |
| 治理规则 | `STRIXNOVA-GOV-REQ-001` 等 | 治理规范 | 1 节 | 遵循并引用 (Referenced)，按规范区分基线与未决候选 |
