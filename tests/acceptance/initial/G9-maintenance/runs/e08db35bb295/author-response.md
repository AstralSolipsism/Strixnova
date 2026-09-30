根据 [AGENTS.md](file:///D:/AboutDEV/Strixnova/.artifacts/validation/d5ba73f19ec8/work/project/AGENTS.md) 与配套 Skill 文件（[SKILL.md](file:///D:/AboutDEV/Strixnova/.artifacts/validation/d5ba73f19ec8/work/project/.agents/skills/strixnova/SKILL.md)、[history-and-upgrade.md](file:///D:/AboutDEV/Strixnova/.artifacts/validation/d5ba73f19ec8/work/project/.agents/skills/strixnova/references/history-and-upgrade.md)）的指引，已在当前新会话中完成显式只读加载与事实查询。相关事实说明如下：

---

### 一、 实际程序与配套 Skill 身份核验

调用指定新入口 `strixnova upgrade runtime`，返回的运行时标识事实如下：

- **程序入口路径**：
  `D:\AboutDEV\Strixnova\.artifacts\validation\d5ba73f19ec8\work\dedicated-installation\versions\7450bb74d1c8738f052e99c46808c89ffe324ba9adf857054a5ea2766ebbb1af\venv\Scripts\strixnova.exe`
- **实际版本号**：`0.1.0.dev0`
- **程序 Build SHA-256**：`67bed3a9172e61e0ed6e120dd8d72fd4080fc8961e032a784a91a483996ad400`
- **依赖锁定摘要 (dependency_lock_sha256)**：`e5fab015ccb16969251e22a734ee5f8dbce0fc1c13f7aeb6554c6389484dc2f6`
- **配套 Skill 目录摘要 (skill_sha256)**：`db7e4104332a19cebf2b9825bb1491911376774d63ac6e9b5a967a7b7e491bb1`（包含 30 个 Skill 文件）
- **格式版本**：Authority v1, Delivery Activities v1, Evidence v1

以上身份哈希与 [AGENTS.md](file:///D:/AboutDEV/Strixnova/.artifacts/validation/d5ba73f19ec8/work/project/AGENTS.md) 声明的 Build 及 Skill 身份完全吻合。

---

### 二、 原事项历史与原始输出保全查询

使用新程序入口对原建设事项 `WI-20260928-F6D5FEEC` 执行只读历史查询（`strixnova history`）：

1. **基本元数据**：
   - **Work Item ID**：`WI-20260928-F6D5FEEC`
   - **标题**：`固定维护保全样例`
   - **状态**：`discussion`（版本：1，创建与更新时间：`2026-09-28T11:03:40.014358Z`）
2. **原始请求（request）**：
   - 记录的 `raw_request`：“保留本轮实际生成的格式和原始输出，用于当前格式的隔离维护。”
3. **事件（events）**：
   - 记录有 1 条历史事件：`event:1`（类型：`work_item_created`，时间：`2026-09-28T11:03:40.014358Z`，有效载荷：140 字节）。
4. **输出保全与执行验证（verifications）**：
   - `verifications.items` 为空（`[]`），当前未生成或关联命令执行输出回执（receipt）。若后续有回执，其原始标准输出/标准错误由系统保全，并可通过 `output:<receipt-id>:stdout` 等只读流按范围读取。
5. **决策与交付（result / delivery / candidates / artifacts）**：
   - 结果状态为 `not_present`，无交付提交（`commits: []`），无候选方案，均处于创建初期的讨论状态，历史事实完整记录且未受本次升级维护破坏。

---

### 三、 维护状态与来源说明

- [maintenance-inputs.json](file:///D:/AboutDEV/Strixnova/.artifacts/validation/d5ba73f19ec8/work/project/maintenance-inputs.json) 记录了维护执行前的初始输入配置（包含原始 source 入口及 target 目标包），当前工程已切换并固定运行在专用的升级后版本目录 `versions/7450bb74...`。
- 本次检查严格执行只读操作，未触发任何业务写入或二次升级。

---

### 四、 加载范围限定说明

**明确界限**：本次操作仅证明了**本新会话根据项目规则及显式指令成功读取并绑定了配套 Skill 与新版本程序入口**；普通宿主环境的通用自动加载机制不在本次检验范围内，未作任何外推。
