# 测试结构与执行策略

本套件按当前行为所有者组织；独立行为各自保留覆盖，运行证据与项目长期材料的状态检查分别报告。

## 结构

`tests/unit` 在最低有效层证明 Module 行为：

- WorkflowAuthority：原子转换、并发冲突、历史、CurrentAction、冲突后重测；
- EngineeringGovernance：方向单一事实、按影响裁剪的工程评估、无语义兜底、SourceReference、紧凑 ImpactScope、AssuranceBand 和规则裁剪；
- ProjectEngineeringBaseline：小型采用/治理清单、独立长期权威定位、ADR 多对多和治理扩展；
- ProjectDomainModel：任意多卷目录、Markdown/YAML 唯一正文、稳定 Fact 身份、闭包和演进；
- ProjectArchitectureDescription（项目架构描述）与 ProjectImplementationAlignment（项目实现对齐）：独立目标架构、完整实现底账、确定性漂移检查和语义确认边界；
- EngineeringTraceProjection：从 Authority、Git 和长期权威重建 current/audit 追溯，不取得写权；
- VerificationRunner：精确命令、去重、失败、超时、not_run、重测和长期引用；
- WorkItemReadModel、Host Adapter、Agent Skill 安装与进程监管的直接合同。

`tests/integration` 只保留关键跨界：

- Git 分支/worktree、并行、冲突、取消和安全清理；
- 七个运行时意图 CLI（命令行接口）与单次完整智能编码代理工程评估路线；
- 领域目录到单 Fact/显式闭包的按需公开读取，不向默认摘要灌入正文；
- 六类代表性完整生命周期：普通修改、新增公共能力并形成 ADR、新项目首个基线、两个并行 WorkItem、原生 Git 冲突、带未合入改动的取消。
- 一条非专业用户自然语言发起、经现有三次确认完成正式领域 Fact 变化的代表生命周期。

同一断言不按活动类型、宿主、语言或风险等级做笛卡尔复制。

`tests/acceptance` 保存跨运行的稳定验收目录，不保存第二套产品状态。引导式形成目录用
`case_id` 区分 50 项当前行为与合同要求，并为每项声明实际读取的英文 Skill 文件。
`scripts/check_guided_formation_acceptance.py` 根据这些依赖的内容指纹报告 `current` 或 `stale`；
它只判断证据是否仍对应当前内容，不判断自然语言回答是否正确。

普通文档、中文审阅和回执编辑不触发 wheel 或 Agent 重验。英文 Skill 批量修改并冻结后，先看
目录中哪些 Agent 场景受影响，再按实际制品依赖和授权范围安排重验。运行代码、CLI、Schema
或打包逻辑按受影响层测试；完整快速套件、全量套件、clean wheel 与隔离安装只在最终候选收口。
wheel SHA-256 标识具体制品，Skill 内容指纹贯通源码、wheel、安装树与 Agent 回执。

## 日常快速套件

```powershell
.venv\Scripts\python.exe scripts\local_validation.py test --pin
```

开发中应进一步缩小到受影响文件。只有跨越 Module 或进入最终验收时才扩大范围。

`tests/integration/test_local_git_lifecycle.py` 只包含上述真实进程、真实 Git 的高成本完整生命周期，因此整组标记为 `slow`；采用 DDD 的事项从三次确认到 ActualResult 的完整 Host 路线、跨调查提交核对同一 Source 的 Fact 变化，以及从 Git/Authority 重建 current/audit 追溯，都需要反复建立和读取真实 Git 历史，单独标记为 `slow`。快速套件保留各 Module 和关键跨界集成，全量再纳入这些高成本历史场景，不靠随意给普通测试贴标签缩短数字。

## 提交前全量

```powershell
.venv\Scripts\python.exe scripts\local_validation.py test --full --pin
```

当前没有把远程 CI、WebUI 或本机未版本化 Authority 混进普通产品套件。wheel 安装和无 Node 的 Agent Skill + CLI 普通运行作为仓库交付验收单独执行，不因每次文档编辑重复触发。

## 性能证据

最终快速套件和全量套件各运行一次，并加 `--durations=25`；只有失败、
明显环境抖动或结果无法解释时才复测。报告：

- 通过、失败、跳过数量；
- pytest 总耗时和外部墙钟时间；
- 最慢测试；
- 测试期间启动的外部进程数；
- 本次候选的源码、环境与运行身份，作为后续可比运行的起点。

`tests.performance.process_count_plugin` 只在显式设置 `STRIXNOVA_TEST_PROCESS_LOG` 并通过 `PYTEST_PLUGINS` 加载时记录成功启动的子进程名称，不记录参数。

测试进程会通过 Git 的进程级配置把 `core.fsmonitor` 设为 `false`。Git for
Windows 的系统级 fsmonitor 会为每个几秒后即删除的临时仓库分离一个常驻
daemon，既不提高测试可信度，又会堆积进程并导致并发套件停滞。该覆盖只传给
pytest 的子进程，不修改用户 Git 配置，也不改变 Strixnova 产品运行行为。

不设置人为时间线。用例减少必须对应已删除职责或重复断言；若耗时没有明显下降或仍超时，继续分析慢项，不能用删除必要覆盖换数字。

## 安装入口检查

源码测试始终使用仓库根 Python 与当前 checkout。三个真实安装探测用例通过 `STRIXNOVA_TEST_INSTALLED_PYTHON` 指向由仓库根 venv 创建、安装本轮 clean wheel 的一次性隔离解释器；不向源码 venv 或系统 Python 安装产品来凑齐探测条件。

未提供该环境时，这三个用例明确跳过，不能计作安装通过。最终 wheel 隔离安装后必须设置该变量并执行这些用例，另外核对原生命令、依赖、包字节与 Skill 身份。
