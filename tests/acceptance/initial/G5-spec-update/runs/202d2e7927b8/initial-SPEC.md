# 工程规格书：修复预约区间结束不大于开始的校验缺陷

> **文档性质与定位**：本文件为根据建设事项 [`inputs/recorded-work-item.json`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/6ea564151824/work/project/inputs/recorded-work-item.json) 中已真实记录的固定隔离事项历史所投影生成的**可阅读工程规格（Reading View / SPEC）**。
> **唯一权威声明**：已记录的建设事项历史与既有长期权威为各自唯一事实与决策来源。本文档作为可读投影，**不构成第二份权威**，不替代原决策确认，亦不因格式化阅读视图而改写任何既有事实。

---

## 1. 规格来源与稳定身份绑定 (Specification Basis & Identity Bindings)

本工程规格严格绑定事项历史中已由负责人确认的方向决策、工程评估与工程方案：

- **所属建设事项**：
  - 事项标识 (`work_item_id`): `WI-20260928-9CA7291C`
  - 事项标题: 修复预约区间结束不大于开始的校验缺陷
  - 事项版本 (`work_item_version`): 19
  - 事项状态 (`status`): `completed`（事项历史记录的事实状态；事项已执行进度仅作为历史事实，不替代规格含义或原确认）
  - 来源文件: [`inputs/recorded-work-item.json`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/6ea564151824/work/project/inputs/recorded-work-item.json) (SHA256: `239be858355a245a4949071972827af50d35e7f494e879f30cdd95253dd46171`)
- **方向决策绑定 (Direction Decision)**：
  - Schema: `strixnova.direction-decision.v1`
  - 确认版本 (`direction_version`): 3
  - 候选指纹 (`candidate_fingerprint`): `sha256:f5a2afd114a4ad47b16a8406f8e78c0fa1c4fbb5a5d4905bc7317873d3e8b06a`
  - 负责人确认状态: `accepted` (已于 2026-09-28T07:30:10.513746Z 确认：“现在理解这份方向说明了，同意这个方向，请继续制定工程方案。”)
- **工程评估与方案绑定 (Engineering Assessment & Plan)**：
  - 评估标识 (`assessment_id`): `EA-20260928-11111111`
  - 评估修订 (`assessment_revision`): 1
  - 方案标识 (`plan_id`): `PLAN-EA-20260928-11111111-R1`
  - 方案指纹 (`candidate_fingerprint`): `sha256:3e50e03c1a956e1cb89ee7abc6d0f4475d603c367ff6cc9aa3b8cf5b7db82e64`
  - 负责人确认状态: `accepted` (已于 2026-09-28T07:48:13.619416Z 确认：“同意当前展示的工程方案，仅在本临时测试工程内实施与验证；实际结果接受前不要提交。”)
  - 治理基线与保障等级: `A1`，治理剖面 `strixnova-general-software-engineering+POLICY-1111111111111111`
- **上游权威基线绑定 (Upstream Authority Baselines)**：
  - 产品定义: `PRODUCT-1111111111111111` (`docs/product/definition.yaml`, `REVISION-1111111111111111`, 基线提交: `086c446f029c89dcfe8e8a78cba643c83b009064`)
  - 领域模型: `MODEL-1111111111111111` (`docs/domain/model.yaml`, `MODELREV-1111111111111111`, 基线提交: `086c446f029c89dcfe8e8a78cba643c83b009064`)
  - 目标架构: `ARCH-1111111111111111` (`docs/architecture/model.yaml`, `ARCHREV-1111111111111111`, 基线提交: `086c446f029c89dcfe8e8a78cba643c83b009064`)
  - 实现对齐: `ALIGNMODEL-1111111111111111` (`docs/engineering/alignment.yaml`, `ALIGNREV-1111111111111111`, 变更集: `AUTHCHANGE-1111111111111111` 生成候选 `ALIGNREV-2222222222222222`)

---

## 2. 变更背景与目标定义 (Purpose, Problem & Scope)

### 2.1 变更背景与核心问题
预约区间计算函数在遇到结束刻度不大于开始刻度（即 `end <= start`）时，原实现未进行有效阻断，仍执行并返回计算结果（如返回 `0` 或负数），导致非法预约时间区间被系统放行，违反领域不变量（预约区间必须具有正时长）。

### 2.2 建设目标 (Goal)
修复预约区间在结束刻度不大于开始刻度时的校验缺陷，显式抛出 `ValueError`；合法正区间保持原有时长计算逻辑，保持函数公共接口签名与类型注解不变。

### 2.3 明确非目标 (Non-Goals)
- 不引入日期、时区或日历解释逻辑。
- 不添加数据持久化层或远程调用服务。
- 不扩展或更改除预约区间时长纯函数以外的其他模块。

---

## 3. 行为契约与需求规范 (Behavioral Contract & Requirements)

本节精确映射并保留方向决策中确立的稳定需求与约束标识，区分系统对外呈现的业务行为要求与具体技术实现细节。

### 3.1 稳定需求条目 (Direction Requirements)

- **`DIRREQ-A1B2C3D4E5F60718`**：
  - **行为定义**：当预约区间的结束刻度不大于开始刻度时（即数学关系满足 $end \le start$），系统必须拒绝该调用并立即抛出标准异常 `ValueError`。
  - **触发条件**：调用预约区间时长计算函数，传入参数满足 $end \le start$（包含结束刻度等于开始刻度的零时长情况，以及结束刻度小于开始刻度的负时长反序情况）。
  - **可观察结果**：调用中断并向调用方抛出 `ValueError` 异常，不产生有效返回值，不产生副作用。

- **`DIRREQ-B2C3D4E5F6071829`**：
  - **行为定义**：对于合法正预约区间（即数学关系满足 $end > start$），系统保持原有返回值逻辑（即返回时长数值 $end - start$），且公共函数接口签名与类型注解保持不变。
  - **触发条件**：调用预约区间时长计算函数，传入参数满足 $end > start$。
  - **可观察结果**：计算并返回正确的整数时长数值（等于 $end - start$）。

### 3.2 稳定设计约束 (Direction Constraints)

- **`DIRCON-C3D4E5F60718293A`**：
  - **约束声明**：严格保持 `duration(start: int, end: int) -> int` 的函数名称、入参个数、入参类型注解及返回值类型注解完全一致，不得改变公共接口暴露形式。

---

## 4. 行为示例与验收准则 (Behavior Examples & Acceptance Criteria)

### 4.1 核心验收准则 (Acceptance Item)

- **`DIRACC-D4E5F60718293A4B`**：
  - **验收陈述**：结束刻度小于或等于开始刻度时抛出 `ValueError`，合法区间返回 `end - start`。
  - **关联需求**：覆盖 [`DIRREQ-A1B2C3D4E5F60718`](#31-稳定需求条目-direction-requirements) 与 [`DIRREQ-B2C3D4E5F6071829`](#31-稳定需求条目-direction-requirements)。
  - **适用性**：必需 (`required`)。

### 4.2 权威行为示例 (Behavior Examples)

方向决策已确认 3 组代表性行为示例，作为可观察验证的基准用例：

#### 示例 1: 合法区间保持原有时长
- **示例标识**: `DIREX-E5F60718293A4B5C`
- **指纹 (SHA256)**: `23a14b0f69ce933d1a05eb3fcb43da320ee6672c4364b17de1952534ae6e4f44`
- **溯源依据**: `DIRREQ-B2C3D4E5F6071829`
- **Given（前置条件）**: `start=10`, `end=60`
- **When（触发操作）**: 调用 `duration(10, 60)`
- **Then（预期结果）**: 返回 `50`

#### 示例 2: 结束刻度等于开始刻度时抛出 ValueError
- **示例标识**: `DIREX-F60718293A4B5C6D`
- **指纹 (SHA256)**: `dc0b0bd5f007e811ada23ad0b81403796a4b2c505136f1fbc226afa33d5fcda2`
- **溯源依据**: `DIRREQ-A1B2C3D4E5F60718`
- **Given（前置条件）**: `start=30`, `end=30`
- **When（触发操作）**: 调用 `duration(30, 30)`
- **Then（预期结果）**: 抛出 `ValueError`

#### 示例 3: 结束刻度小于开始刻度时抛出 ValueError
- **示例标识**: `DIREX-0718293A4B5C6D7E`
- **指纹 (SHA256)**: `b96edff429fa847302fa1b4518ea7e316c343844aca6437dab1d4acb05e0c229`
- **溯源依据**: `DIRREQ-A1B2C3D4E5F60718`
- **Given（前置条件）**: `start=50`, `end=20`
- **When（触发操作）**: 调用 `duration(50, 20)`
- **Then（预期结果）**: 抛出 `ValueError`

---

## 5. 工程实现方案与方案处置 (Engineering Design & Plan Disposition)

本节明确工程实现方案的设计决策、操作清单与切片处置，区分“应有的系统行为”与“技术实现细节”，对方案全要素进行处置说明。

### 5.1 架构设计与技术选型
- **设计决策**：在纯函数模块 `src.py` 的 `duration` 函数入口处添加守卫条件（Guard Clause）：`if end <= start: raise ValueError(...)`。
- **替代方案权衡**：
  - 方案 A（已采纳）：在纯函数内部做前置判断。直接维护模块高内聚与领域不变量，从源头彻底阻断脏数据。
  - 方案 B（未采纳）：由外部调用方自行做防御性校验。该方案将校验责任分散在各调用方，核心函数依然存在漏洞，且易因调用方遗漏导致非法区间穿透，故予以否决。
- **影响范围 (Impact Scope)**：
  - 受影响维度：`testing`（需补充针对 $end \le start$ 异常分支的自动化测试断言）。
  - 无影响维度：`user_behavior`, `product_scope`, `domain`, `architecture`, `interface`, `data`, `security_privacy`, `quality_performance`, `operations_deployment`, `compatibility_migration`, `documentation_support`。

### 5.2 实施切片划分 (Implementation Slices)
方案规划了单一完备切片以保证原子性变更：
- **切片标识**: `SLICE-001`
- **切片目标**: 修复代码缺陷并刷新实现对齐底账与基线。
- **实施操作清单**: 承载 `operations[0]` 至 `operations[7]` 共 8 项操作。
- **回滚与恢复策略**: 若实施或验证失败，通过 Git 恢复工作区并重新审查校验条件。

### 5.3 工程操作全要素处置 (Operations Disposition)

方案规划的 8 项工程操作均已建立明确归属与处置说明：

1. **`operations[0]` (代码修改)**：
   - 路径: `src.py`
   - 动作: `modify`
   - 承载需求: `DIRREQ-A1B2C3D4E5F60718`, `DIRREQ-B2C3D4E5F6071829`
   - 处置: 解释并纳入规格，在函数入口增加 `end <= start` 时抛出 `ValueError` 的逻辑。
2. **`operations[1]` (测试用例补充)**：
   - 路径: `tests/test_duration.py`
   - 动作: `modify`
   - 承载需求: `DIRREQ-A1B2C3D4E5F60718`, `DIRREQ-B2C3D4E5F6071829`
   - 处置: 解释并纳入规格，增加针对 $end = start$ 和 $end < start$ 抛出 `ValueError` 的 pytest 断言。
3. **`operations[2]` (对齐根文件更新)**：
   - 路径: `docs/engineering/alignment.yaml`
   - 动作: `modify` (修改长期产物 `ALIGNMODEL-1111111111111111`)
   - 承载需求: `DIRREQ-A1B2C3D4E5F60718`
   - 处置: 解释并纳入规格，更新实现对齐模型根配置。
4. **`operations[3]` (源码归属底账刷新)**：
   - 路径: `docs/engineering/source-ownership.yaml`
   - 动作: `modify`
   - 承载需求: `DIRREQ-A1B2C3D4E5F60718`
   - 处置: 解释并纳入规格，更新受管文件散列指纹。
5. **`operations[4]` (实际关系底账刷新)**：
   - 路径: `docs/engineering/actual-dependencies.yaml`
   - 动作: `modify`
   - 承载需求: `DIRREQ-A1B2C3D4E5F60718`
   - 处置: 解释并纳入规格，更新代码实际依赖关系底账。
6. **`operations[5]` (目标责任底账刷新)**：
   - 路径: `docs/engineering/target-responsibilities.yaml`
   - 动作: `modify`
   - 承载需求: `DIRREQ-A1B2C3D4E5F60718`
   - 处置: 解释并纳入规格，刷新模块责任对齐状态。
7. **`operations[6]` (偏离底账刷新)**：
   - 路径: `docs/engineering/deviations.yaml`
   - 动作: `modify`
   - 承载需求: `DIRREQ-A1B2C3D4E5F60718`
   - 处置: 解释并纳入规格，消除已知实现偏离缺口。
8. **`operations[7]` (基线配置更新)**：
   - 路径: `docs/engineering/baseline.yaml`
   - 动作: `modify`
   - 承载需求: `DIRREQ-A1B2C3D4E5F60718`
   - 处置: 解释并纳入规格，使工程基线指向新的对齐候选。

---

## 6. 验证安排与策略 (Verification Targets & Commands)

### 6.1 验证命令规范 (Verification Command)
- **命令标识**: `VC-001`
- **运行类型**: `targeted_test`
- **执行程序**: `D:\AboutDEV\Strixnova\.venv\Scripts\python.exe`
- **执行参数**: `-m pytest tests/test_duration.py -q`
- **覆盖目标**: `DIREX-E5F60718293A4B5C`, `DIREX-F60718293A4B5C6D`, `DIREX-0718293A4B5C6D7E`, `DIRCON-C3D4E5F60718293A`

### 6.2 验收目标与命令绑定 (Target Verification Bindings)
1. **约束验证**: `DIRCON-C3D4E5F60718293A`
   - 方式: `command` (`VC-001`)。通过测试套件针对函数签名的实际调用与静态导入确保签名不变。
2. **示例验证**:
   - `DIREX-E5F60718293A4B5C` $\rightarrow$ `tests/test_duration.py::test_valid_interval_keeps_its_duration`
   - `DIREX-F60718293A4B5C6D` $\rightarrow$ `tests/test_duration.py::test_equal_marks_raise_value_error`
   - `DIREX-0718293A4B5C6D7E` $\rightarrow$ `tests/test_duration.py::test_reversed_marks_raise_value_error`
   - 均要求 Agent 断言充分性审阅 (`assertion_review_required: true`)，不以测试命令退出码为唯一充分性证明。
3. **复合验收验证**: `DIRACC-D4E5F60718293A4B`
   - 方式: `examples`。由上述 3 项子示例的真实证据及断言审阅派生组合判定。

---

## 7. 事项执行事实与已知限制 (Progress Facts & Known Limitations)

> **原则说明**：本节陈述的事项执行进度与回执数据仅作为工程历史进度的事实记录，**不替代上述规范含义或原确认**。

### 7.1 进度事实记录
- **验证回执**: `VR-WI-20260928-9CA7291C-F472B33294`（执行命令 `VC-001`，命令状态为 `passed`）。
- **实际结果确认**: 负责人已于 2026-09-28T08:02:36.554746Z 确认实际结果（候选指纹 `sha256:c7b8ba9d7619303abd40270b3da8baa624d6f4e063b26e3af8c9766fae00ec7a`）。
- **代码提交与合入**:
  - 工作提交 (`result_commits`): `071b446e7658239d3b3081ac2b5ddbcf47f2eb15`
  - 集成合入 (`integrated_commit`): `30c96c7ea14df68b959043177eae03edba0f0a3a` (合入至 `main` 分支)

### 7.2 真实限制记录 (Limitations)
- **测试报告路径差异**: 在 pytest 报告收集过程中，测试用例路径携带了宿主绝对工作区前缀，导致基于相对路径的自动用例映射存在测试根差异标记；通过 Agent 逐项断言审阅结合测试命令真实通过结果，证明了代码行为符合预期。
- **语义证明边界**: 本事项所有语义内容与断言审阅均未声称机器严格证明 (`semantic_content_machine_proven: false`)，其语义有效性依赖智能编码代理的分析与项目负责人的真实确认。

---

## 8. 全要素覆盖索引 (Coverage Index)

本索引对照已确认方向决策与工程方案，核验本规格文档对所有稳定标识与操作要素的覆盖情况：

| 要素类别 | 原始稳定标识 / 要素 | 对应规格章节 | 覆盖与处置状态说明 |
|---|---|---|---|
| 方向需求 (Requirement) | `DIRREQ-A1B2C3D4E5F60718` | 3.1 节 | 完全覆盖 (Represented)，定义 $end \le start$ 抛出 ValueError 行为 |
| 方向需求 (Requirement) | `DIRREQ-B2C3D4E5F6071829` | 3.1 节 | 完全覆盖 (Represented)，定义 $end > start$ 正常返回与接口不变 |
| 方向约束 (Constraint) | `DIRCON-C3D4E5F60718293A` | 3.2 节 | 完全覆盖 (Represented)，约束保持 duration 签名与类型注解不变 |
| 方向验收 (Acceptance) | `DIRACC-D4E5F60718293A4B` | 4.1 节 | 完全覆盖 (Represented)，由 3 个子示例派生综合验收 |
| 行为示例 (Example) | `DIREX-E5F60718293A4B5C` | 4.2 节 | 完全覆盖 (Represented)，合法区间保持原有时长 (10, 60 -> 50) |
| 行为示例 (Example) | `DIREX-F60718293A4B5C6D` | 4.2 节 | 完全覆盖 (Represented)，相等刻度抛错 (30, 30 -> ValueError) |
| 行为示例 (Example) | `DIREX-0718293A4B5C6D7E` | 4.2 节 | 完全覆盖 (Represented)，反序刻度抛错 (50, 20 -> ValueError) |
| 工程操作 (Operation) | `operations[0]` (`src.py`) | 5.3 节 | 完全处置 (Disposed)，前置条件添加 |
| 工程操作 (Operation) | `operations[1]` (`tests/test_duration.py`) | 5.3 节 | 完全处置 (Disposed)，补充测试断言 |
| 工程操作 (Operation) | `operations[2]` (`docs/engineering/alignment.yaml`) | 5.3 节 | 完全处置 (Disposed)，实现对齐根文件更新 |
| 工程操作 (Operation) | `operations[3]` (`docs/engineering/source-ownership.yaml`) | 5.3 节 | 完全处置 (Disposed)，源码归属散列更新 |
| 工程操作 (Operation) | `operations[4]` (`docs/engineering/actual-dependencies.yaml`) | 5.3 节 | 完全处置 (Disposed)，实际关系底账更新 |
| 工程操作 (Operation) | `operations[5]` (`docs/engineering/target-responsibilities.yaml`) | 5.3 节 | 完全处置 (Disposed)，目标责任对齐更新 |
| 工程操作 (Operation) | `operations[6]` (`docs/engineering/deviations.yaml`) | 5.3 节 | 完全处置 (Disposed)，偏离消除 |
| 工程操作 (Operation) | `operations[7]` (`docs/engineering/baseline.yaml`) | 5.3 节 | 完全处置 (Disposed)，基线指向新对齐候选 |
| 实施切片 (Slice) | `SLICE-001` | 5.2 节 | 完全覆盖 (Represented)，原子切片承载全部 8 项操作 |
| 验证命令 (Command) | `VC-001` | 6.1 节 | 完全覆盖 (Represented)，pytest 验证命令与测试用例映射 |
| 长期产物变更 (Authority Change) | `ALIGNMODEL-1111111111111111` | 1 节, 5.3 节 | 完全覆盖 (Represented)，更新实现对齐模型候选 |
| 治理规则 (Governance Rule) | `STRIXNOVA-GOV-REQ-001` | 1 节 | 遵循并引用 (Referenced)，需求、约束与验收规范 |
| 治理规则 (Governance Rule) | `STRIXNOVA-GOV-LIFE-001` | 1 节, 5 节 | 遵循并引用 (Referenced)，生命周期与配置操作规范 |
| 治理规则 (Governance Rule) | `STRIXNOVA-GOV-TEST-001` | 6 节 | 遵循并引用 (Referenced)，验证与测试设计规范 |
