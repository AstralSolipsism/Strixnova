# 协作开发

本仓库当前是 Strixnova `0.1.0.dev0` 的协作开发源码。Agent 机械负担改进的 11 项产品侧实现已落地；受影响程序检查已完成，真实 Agent 回归仍待执行。具体边界见[当前验证状态](docs/engineering/validation-status.md)和[逐项实施记录](docs/研究/2026-09-30-Agent机械负担减负实施记录.md)。

## 开始开发

1. 克隆仓库，进入目录，在自己的分支上工作：

   ```powershell
   git clone https://github.com/AstralSolipsism/Strixnova.git
   cd Strixnova
   git switch -c <your-branch>
   ```

2. 按 [AGENTS.md](AGENTS.md) 使用 Windows、Python 3.12、Git 和 uv。首次创建仓库环境并安装锁定依赖：

   ```powershell
   uv venv --python 3.12 .venv
   uv pip install --python .venv\Scripts\python.exe --require-hashes -r requirements-dev-win-py312.txt -r strixnova\requirements-lock-win-py312.txt
   uv pip install --python .venv\Scripts\python.exe --no-deps --no-build-isolation --editable .\strixnova
   ```

   已有 `.venv` 时直接复用。开发态 editable 安装不构成交付 wheel 或隔离安装验收证据。

3. 运行受影响测试。例如，修改准备输入接口后：

   ```powershell
   .venv\Scripts\python.exe scripts\local_validation.py test -- tests\unit\test_prepared_input.py
   ```

   根据实际影响增加对应单元或集成用例。完整候选验收另有明确范围；普通协作改动不自动重跑全量、构建或真实 Agent 场景。

## 代码入口

| 位置 | 职责 |
| --- | --- |
| `strixnova/src/strixnova/` | 产品 Python 源码；`host_adapter.py` 为结构化入口，`application_coordinator.py` 协调现有用例。 |
| `strixnova/src/strixnova/prepared_input.py` | 固定动作上下文、结果清单、语义增量组装、引用和预检。 |
| `strixnova/src/strixnova/resources/agent-skill/strixnova/` | 唯一正式随包 Skill；`skills-cn/strixnova/` 是中文审阅副本。 |
| `tests/unit/`、`tests/integration/`、`tests/repository_checks/` | 功能回归与仓库状态检查分层；后者须显式选择。 |

程序只处理结构、身份、范围、版本、散列和确定性事实。语义、证据充分性及重测必要性由 Agent 判断，接受由负责人决定。准备文件不是新的权威或批准记录；不把漏项自动填成接受、实现、满足或支持。

开发 Strixnova 本身使用普通 Git，不用 Strixnova 管理自身或创建真实 WorkItem。各协作者使用独立分支和工作目录，避免同时改写同一工作树。遵守已有的结果确认、提交和远程操作授权边界。

`.venv/`、`.artifacts/`、缓存和本机运行数据不进入 Git。`tests/acceptance/initial/` 保留按原内容绑定的证据，修改源码不代表旧证据仍匹配；不要为使状态全绿改写旧指纹或结论。部分证据中的绝对路径只是原执行现场，不是新协作者必须复制的目录。

本次源码同步没有更新发行包、安装树或正式发布。构建交付 wheel 仍只使用 `.venv\Scripts\python.exe scripts\build_clean_wheel.py`；其他开发约束和验收层级见 [AGENTS.md](AGENTS.md)。
