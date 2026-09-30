# AGENTS.md

## Strixnova 暂停作为工作流使用

本项目仍在开发。除非项目负责人明确要求继续开发 Strixnova 本身，否则不要调用 Strixnova CLI、Skill、插件或 hooks，也不要用 Strixnova 管理其他项目。

开发 Strixnova 本身时也不用 Strixnova 管理 Strixnova，不创建或修改 WorkItem；使用普通本地 Git 和本文件约束。

## Python 环境

一切 Python 命令必须使用仓库根 `.venv\Scripts\python.exe`，Python 3.12。禁止裸调用 `python`、`python3`，禁止向系统 Python 安装 Strixnova 或其依赖。系统解释器产生的测试结果无效。

唯一例外是最终 wheel 安装验收：必须由仓库根 venv 创建一次性隔离 venv，并只用该隔离解释器检查已安装 wheel、运行依赖和 CLI；它不能替代源码测试，也不得安装到系统 Python。

本项目当前不使用 CI。测试、构建与安装验收在本地按本文件执行；不新增或恢复 `.github/workflows/` 工作流。重新启用 CI 须由项目负责人明确决定。

本地测试与构建工具的版本锁定在 `requirements-dev-win-py312.in` / `requirements-dev-win-py312.txt`；运行依赖继续使用 `strixnova/requirements-lock-win-py312.txt`。

wheel 只能通过 `.venv\Scripts\python.exe scripts\build_clean_wheel.py` 构建。该入口从排除 `build`、`dist`、`*.egg-info` 和缓存的临时源码快照构建，并逐字节核对随包资源；不得直接对仓库源目录运行 `python -m build` 作为交付证据。

## 测试

### 验收执行者

- Agent 行为及语义验收禁止使用 Codex 主 Agent 或子 Agent；Codex 的演练、复核和模拟负责人答复不能计为验收通过。真实 Agent 验收使用 Antigravity CLI，保留具体模型、调用、输入、权限、原始事件及产物。
- Codex 可以准备隔离夹具、收集记录和运行确定性检查；pytest、构建及文件核对仍只证明各自机器检查范围，不替代 Agent 验收或负责人接受。
- 负责人已允许本轮新项目隔离验收使用运行前公开并固定的负责人角色测试输入；由真实 Antigravity 执行和独立 Antigravity 复核。具体输入和边界见 docs/engineering/agent-acceptance.md。Codex 不承担语义裁决，测试接受不代表真实项目结果接受。
- Antigravity 遇权限或环境阻断时，保留待验并给负责人提供明确的本机操作步骤，不得改用 Codex Agent 将场景标为通过。

先按下方触发规则确定是否需要验证及其范围。需要源码测试时，先运行受影响测试，并统一通过本地验证入口，沿用原 pytest 套件与并发参数：

```powershell
.venv\Scripts\python.exe scripts\local_validation.py test --pin
.venv\Scripts\python.exe scripts\local_validation.py test --full --pin
```

不要机械地为每次修改运行全量，不要为缩短数字删除独立行为覆盖。

### 功能回归与仓库状态检查

- `tests/unit` 和 `tests/integration` 是默认功能回归范围。验证证据复用、漂移识别等程序行为时，使用固定、隔离、自洽的项目样例，不把当前 Strixnova 工作树当作“源码未变化”的测试前提。
- `tests/repository_checks` 核对本仓库当前源码、长期材料和已登记快照是否一致，需显式运行：`.venv\Scripts\python.exe scripts\local_validation.py test -- tests\repository_checks`。它不混入默认快速或全量功能套件。
- 仓库状态检查的失败仍须报告，但应与功能回归失败分开说明；不得删掉约束或只替换指纹来制造通过。进入明确的完整候选验收时，单独检查相应仓库状态并报告结果。

### 临时工作区与保留规则

- 定点测试使用 `.venv\Scripts\python.exe scripts\local_validation.py test -- tests\unit\test_example.py`，通过 `--` 传递 pytest 参数；不另设散落的 `--basetemp`、JUnit 或缓存目录。
- 每次运行在 `.artifacts/validation/<运行ID>/` 内隔离 `work/` 和 `evidence/`。成功后自动删除 `work/`；普通成功报告保留最近 3 轮，失败的工作区及报告保留 7 天。
- 需要继续检查临时明细或交给异步 Agent 的目录，执行时加 `--keep-workspace`；最终证据加 `--pin`。正在运行、未收口、未知归属的目录不自动删除。异步 Agent 结束后，由操作者确认收口再释放目录。
- 运行 `.venv\Scripts\python.exe scripts\local_validation.py clean` 处理到期记录。显式 `clean --release <运行ID>` 会删除该已结束运行的工作区和证据，必须先确认必要证据和 wheel 已保存到正式位置。
- 仅回收已结束工作区时使用 `clean --release-workspace <运行ID>`，保留并固定该轮证据、日志和结果；运行中或进程结束未确认时仍拒绝。先保全工作区内的唯一证据和 wheel，再释放目录。
- 其他前台命令验收可用 `local_validation.py run --label <用途> -- <明确命令及参数>`；额外证据写入 `STRIXNOVA_VALIDATION_EVIDENCE`，临时文件写入 `STRIXNOVA_VALIDATION_WORK`。需要保留的 wheel 写入 `.artifacts/candidates/` 或明确的证据目录。
- 清理只处理带匹配归属记录的验证目录，不扫描或删除真实项目的 `.strixnova`、开发环境、历史归档和普通宿主安装；清理失败必须显示并保留诊断，不能以退出码 0 掩盖当前工作区未回收。

具体用法与证据保留边界见 [本地验证与临时产物管理](docs/使用说明/本地验证与临时产物管理.md)。

### 验证触发与候选冻结

- 用户明确要求本轮不测试或不验收时，不运行相应流程，也不得通过检查脚本、构建或其他入口间接执行；结果说明如实标注未运行。普通文件阅读、编辑与内容复核不代表测试或验收通过。
- 普通文档、`AGENTS.md`、`skills-cn/` 审阅文本或证据记录变化，默认只做内容复核；实际涉及格式、引用或同步关系时，才运行对应的必要检查。不因此触发源码测试、wheel 构建、隔离安装或 Agent 演练。
- 英文随包 Skill 的局部方法、示例或措辞调整，先判断实际改变了哪些 Agent 行为。语义不变的措辞只做内容与必要的一致性检查；行为变化只做覆盖该变化的定点场景验证，并同步审阅副本。不得默认从零建立业务项目、重演完整 Git 交付或重跑全部引用该文件的场景。
- 需要核对旧证据是否仍匹配时，使用 `scripts\check_guided_formation_acceptance.py`。`stale` 表示旧证据所依赖的内容已变，不等于功能失败，也不自动触发完整验收。普通迭代允许保留并说明失效、待验或受阻状态；不得为使清单全部变绿扩大任务，也不得仅刷新指纹就把未重验的场景标为通过。
- 运行源码、CLI 或 Schema 变化，先运行受影响的单元与集成测试。Skill 改变授权、确认、状态推进、写入或恢复等关键行为时，增加对应的真实流程回归。只有变化涉及打包、安装态行为，或已进入明确的完整候选验收范围时，才增加 clean wheel 与隔离安装。
- 完整候选验收是单独明确的交付范围；不得把普通修改、完成任务或本地提交自动提升为这一层级。进入该范围且内容冻结后，再运行快速套件、全量套件、一次 clean wheel、隔离安装及需补齐的 Agent 场景；仍匹配的证据继续沿用，失效或待验的必需场景未完成时不能宣称完整候选已验收。
- Agent 回归优先复用已经准备好项目配置、已采用权威和基线的固定夹具。只有验证首次接入、初始化或升级本身时，才从相应初始状态开始；不得为一次局部指引调整重复建立整套项目治理材料。
- 验证前说明所选层级、范围、预计耗时和停止条件。小幅指引调整按定点验证安排，不默认开展小时级项目演练；接近预计耗时仍未收口时，先说明完成、剩余和受阻项，不自动追加场景、重建夹具或增加 Agent。
- 场景经有限定位确认受阻于与本轮无关的既有程序或环境问题时，保留必要证据并停止该场景，继续不受影响的工作，把该问题单独列出。不得通过反复改造业务夹具、迁移布局或重规划来追求通过。本轮改动引入的问题仍应修复，并重跑受影响层；失败或修复不得被描述为首次即通过。
- `scripts\skill_bundle_manifest.py` 的内容指纹用于核对源码 Skill、wheel Skill、安装树和 Agent 回执是否为同一文件内容；wheel SHA-256 仍只标识那一个具体交付制品，两者不得互相替代。
- 修复若改变已冻结内容，只重跑受影响层及必要的最终收口，不在每次文本编辑后重复整套流程。

## 交付顺序

本项目采用“实施未提交修改 → 按变更范围完成必要验证 → 向项目负责人展示实际结果与验证边界 → 用户确认 → 组织原子提交 → 本地合入和清理”。只有交付范围明确包含完整候选验收时，才加入上述全量、构建、安装和 Agent 场景验收；用户要求本轮不测试或不验收时，保留未运行说明，不以完整候选已验收的名义交付。

在实际结果确认前不暂存或提交代码。不得执行远程 Git 操作，不得修改或删除用户未跟踪目录。
