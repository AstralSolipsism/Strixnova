已根据第二份声明来源（同一事项的未接受方向候选第 4 版，[`inputs/source-view.json`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/202d2e7927b8/work/project/inputs/source-view.json)）完成 [`docs/reading/SPEC.md`](file:///D:/AboutDEV/Strixnova/.artifacts/validation/202d2e7927b8/work/project/docs/reading/SPEC.md) 的更新。

---

### 一、更新的核心内容与依据对照

1. **来源绑定区分（基线 vs 候选）**：
   - **既有已确认基线**：保留 `direction_version: 3` 及其候选指纹（`sha256:f5a2afd114a4ad47b16a8406f8e78c0fa1c4fbb5a5d4905bc7317873d3e8b06a`）和真实历史确认记录。
   - **当前未接受候选**：映射 `direction_version: 4`，明确其状态为草案 `draft`，标记 `owner_accepted_by_this_input: false`（负责人尚未接受该方向），确认语义源已发生变动（`semantic_sources_changed: true`）。

2. **行为契约与稳定身份更新**：
   - **不受影响的稳定身份**：
     - `DIRREQ-A1B2C3D4E5F60718`（$end \le start$ 抛出 `ValueError`）保持原样不变。
     - `DIRCON-C3D4E5F60718293A`（保持 `duration(start: int, end: int) -> int` 签名与类型注解不变）保持原样不变。
     - 既有行为示例 `DIREX-E5F60718293A4B5C`、`DIREX-F60718293A4B5C6D`、`DIREX-0718293A4B5C6D7E` 保持原样不变。
   - **受影响及新增候选条目**：
     - `DIRREQ-B2C3D4E5F6071829`：更新为候选修订条目，增补“合法区间长度不超过 480 分钟”的前置条件。
     - `DIRREQ-18293A4B5C6D7E8F`：新增候选需求，明确“正区间长度大于 480 分钟时抛出 `ValueError`；恰好 480 分钟仍接受”。
     - `DIRACC-D4E5F60718293A4B`：更新验收陈述为“结束不晚于开始或正区间长度大于 480 分钟时抛出 `ValueError`；其余正区间返回 `end - start`”。
     - 新增候选行为示例：`DIREX-18293A4B5C6D7E8F`（恰好 480 分钟，`start=20, end=500 -> 480`）与 `DIREX-293A4B5C6D7E8F90`（超过 480 分钟，`start=20, end=501 -> ValueError`）。

3. **旧方案处置与缺口声明 (Plan Disposition & Gaps)**：
   - 明确指出既有工程方案（`PLAN-EA-20260928-11111111-R1`，操作项 `operations[0]` 至 `operations[7]`）系针对方向第 3 版制定，**尚未为 480 分钟上限新规则重评**。
   - 明确揭示待决缺口：
     - 代码实现缺口（尚未规划或实现 480 分钟拦截）；
     - 验证覆盖缺口（既有 `VC-001` 仅绑定前 3 组示例，2 组新增候选示例尚无绑定命令或测试用例）；
     - 治理决策缺口（未接受的方向候选不能直接作为已批准的技术实施方案）。
   - 未虚构任何新方案、测试回执或接受记录，仅作为规格阅读投影反映当前治理与规范事实。
