# Strixnova 仓库目录与开发工具约定

本文件整理本仓库既有布局、开发边界和证据保留要求，由工程政策引用。它不规定其他受管项目采用同样目录，也不改变产品领域事实或目标模块职责。新文件的语义职责由 Agent 调查和说明，程序不根据文件名推断业务含义。

## 文件放置与职责

| 位置 | 放置内容及维护要求 |
| --- | --- |
| `strixnova/src/strixnova/` | 随包运行代码及资源。沿用现有模块职责与归属登记；不为目录对称性搬动源码。新增文件先说明承担的既有职责，无法归属时保留调查缺口。 |
| `strixnova/src/strixnova/resources/agent-skill/strixnova/` | 唯一随包 Skill。内容身份按实际文件字节计算，变更后同步中文审阅材料；不得把外部验收驱动引入产品。 |
| `tests/unit/`、`tests/integration/`、`tests/support/` | 隔离的行为回归和公共夹具。Python 用例沿用 `test_*.py`；支持资料不能代替真实回执。 |
| `tests/repository_checks/` | 显式执行的本仓库材料、来源及配置一致性检查，不混入默认功能回归。 |
| `scripts/` | 长期维护的开发入口：验证、构建、证据登记及外部验收驱动。可重用入口接受明确参数；一次性诊断脚本留在归属清楚的 `.artifacts/` 运行目录。 |
| `docs/domain/`、`docs/architecture/`、`docs/implementation-alignment/` | 分别维护领域、目标架构和实际实现记录。实际路径归属属于实现对齐，不能把当前布局当作目标职责。 |
| `docs/领域模型阅读版/`、`docs/使用说明/` | 供人阅读的说明，按对应正式来源更新；来源变化需要复核，文档存在或编号齐全不等于含义正确。 |
| `.artifacts/validation/<运行ID>/work/`、`evidence/` | 前者放临时项目和环境，后者放应保留的检查证据。唯一证据不能只存放在待释放工作区。 |
| `tests/acceptance/` | 正式验收索引、必要回执和可恢复的原始记录。大量重复快照不得逐次展开入库；历史记录不改写为首次通过。 |

普通 Python 源码沿用小写下划线命名；已有历史文件不为统一名字强制改名。文档按当前用途目录归档，不以名称匹配推断规则含义。移动文件必须处理调用、引用和归属记录；同名文件按仓库身份区分。

## 关键开发工具边界

这些工具属于本仓库开发过程，受本约定和 AGENTS.md 管理；不伪称已经纳入[产品运行包归属清单](../implementation-alignment/source-ownership.yaml)。

| 职责 | 现有入口 | 必要检查 |
| --- | --- | --- |
| 外部 Agent 传输、事件采集、原文附引 | `scripts/agent_acceptance.py`、`scripts/acceptance_evidence.py` | 命令、输入、输出、权限和引用身份有真实记录；程序不产生语义通过结论。对应 `test_agent_acceptance.py`、`test_acceptance_evidence.py`。 |
| 独立复核及场景执行 | `scripts/review_antigravity_evidence.py`、`scripts/run_antigravity_*.py`、`scripts/run_rule_enforcement_acceptance.py` | 留在开发工具侧；测试范围、固定输入和评审结论分别保留。改动需要 Agent 行为验收时，按本轮用户授权执行；禁止时明确未验。 |
| 验收目录当前性 | `scripts/check_guided_formation_acceptance.py` | 只比较已声明依赖与原始摘要，分别报告未登记、变化和待验；不把 Skill 一致冒充整个执行条件一致。对应 `test_guided_formation_acceptance.py`、`test_acceptance_dependency_freshness.py`。 |
| 运行目录与释放 | `scripts/local_validation.py` | 复用既有进程监督、锁、路径与归属检查；保留证据的释放与完整释放区分。对应 `test_local_validation.py`。 |
| 构建、安装与 Git 检出 | `scripts/build_clean_wheel.py`、`scripts/check_package_checkout.py`、`scripts/build_offline_bundle.py`、`scripts/check_offline_installation.py` | 只有 clean wheel 是构建入口；检出检查不构建、不暂存、不安装。对应构建、检出及离线安装测试。 |
| 内容身份与许可 | `scripts/skill_bundle_manifest.py`、`scripts/check_skill_cn_sync.py`、`scripts/third_party_notice.py` | 原字节身份、审阅同步和根 README 唯一许可正文分别核对，不用同一版本号代替同一内容。 |

脚本修改的方案需要指出所属职责、调用方和受影响检查；语义判断仍由 Agent 完成。开发工具可以调用已授权的外部 Agent，产品运行包仍不得因此新增 Agent 调度能力。本地验证外层保留已授权 Antigravity（`agy`）验收进程的调用能力；产品内部使用完整的禁止 Agent 名称政策。开发调用仍受 AGENTS.md 和本轮用户授权约束，外层允许执行不代表语义验收授权。

## 核验和收尾

工程方案沿现有操作、约束、验证命令及实际结果引用记录本次约定的落实。尚未建设规则 ID 直接作为核验目标的新合同；不得声称本文件的每句话都已由机器自动强制执行。

1. 按 AGENTS.md 运行受影响验证；用户禁止调用 Agent 时，不通过测试或包装脚本间接启动。
2. 保存必要输入、失败和最终回执；同一份未变化材料用身份引用复用，避免重复工作区快照。
3. 确认执行结束、唯一证据及 wheel 已保全后，使用 `clean --release-workspace <运行ID>` 释放工作区，保留记录。未知和仍运行的目录不释放。
4. 用户确认实际结果后才暂存。暂存完成后可通过本地验证入口运行 `scripts/check_package_checkout.py --wheel <候选wheel>`，核对暂存索引真实检出与冻结源码、wheel；未暂存源码、换行转换或 wheel 不一致均报告差异。该检查不代表宿主已经安装或 Agent 已加载。

新约定若与现行工程政策矛盾，进入既有政策修订流程；不得临时放行来制造通过，也不得自行增加一套审批状态。
