# 当前验证状态

版本：0.1.0.dev0。初始候选仍在验收；尚未取得负责人对实际重构结果的接受，也未暂存、提交或发布。

| 范围 | 已有结果 | 当前边界 |
| --- | --- | --- |
| 快速功能回归 | 1139 通过，5 跳过，含三项真实隔离安装探测 | 四项文件符号链接检查受宿主权限限制，一项文件名规则不适用于 Windows |
| 全量功能回归 | 1143 通过，4 失败，8 跳过；25 分 29 秒 | 三个依赖真实未提交基线的功能夹具已隔离并通过定点复验；真实基线检查移入仓库状态层保留。原失败没有改写为首次通过 |
| 技术复核与修复 | 已知 Agent 拒绝修复69项回归通过；当前合同清理51项回归通过 | 新回归先复现外部GIT_DIR干扰失败，删除无用读取后通过；旧表示回退已退出。机器验证与独立重核分别保留 |
| 最新源码观察与实现评价 | 135 个受管文件，60 个 Python 源码，664 条规范化关系 | 21 个模块、83 条关系和 33 条约束已有当前原生评价及独立复核；其中 1 项保留部分或未满足状态，原缺口和补验要求仍在；剩余 0 条关系、0 条约束待评价。模块和约束评价不等于完整 Agent 流程验收 |
| 最新 clean wheel 与隔离安装 | 135 个源码、wheel 和安装文件匹配；9 次安装及原生入口调用通过 | 未安装到系统或源码环境；不表示普通宿主自动加载或正式发布 |
| 真实 Agent 证据 | 50 项目录中，40 项声明依赖与证据当前有效、0 项需重核、10 项待验 | 当前策略 G1 已完成新的实际执行和三项独立复核；原越界失败、服务 EOF 与纠正保留。固定输入下通过不代表真人接受或任意输入下的可靠性 |
| 复杂流程验收 | 22:20后恢复实际原生执行，两次有限调用仍未完成新评估提交 | 当前版本13停在submit_engineering_assessment；未投递新接受、未实施业务，原拒绝及超时保留；此场景停止追加，先完成不依赖它的检查 |
| 仓库材料与 Git checkout | 原仓库状态检查 6 通过、8 未通过；checkout 因属性未暂存而拒绝 | 三份正式 Git 绑定仍为空；当前 137/137 项实现目标已有评价，7 条工程保障规则待评价。原字节相等不等于索引 checkout 通过 |
| 负责人实际结果接受 | 待完整可审阅结果形成 | 隔离测试中的固定接受不授权真实仓库提交、推送或发布 |

最新候选位于本地 `.artifacts/candidates/initial-alignment-clean/`。wheel SHA-256：`f71c0e7d19da20db54ad64b2383c9d95d986b288299d13b71f9927953fe375e8`；Skill 摘要：`084fb9187265c798db2ebb6c9edc13a2545d7cde4c1446674a4414629f04e84b`。135个源码/wheel/安装文件匹配，9次安装与命令检查通过；不代表完整Agent、Git或负责人接受。

修复前的本地记录：快速 `f5e20647248e`，全量 `d0856323c4b6`，修复层 `7aaf327a1ccb`，该轮观察 `8216d2c84e13`，wheel `308a4b4949e2`，离线包 `2b4fc62609a7`，隔离安装 `1dc202780cbc`，源码/制品注册 `f88e7668b02e`，仓库状态 `8b07f3a022b4`，checkout 阻断 `8a1262000350`。本次同步和构建先因同步清单滞后而拒绝，补齐后通过；原 `19621d5bd348`、`63b2a9a23508` 仍保留，不伪称首次通过。

逐项结果、原始记录及当前性以[验收目录](../../tests/acceptance/guided-formation-cases.yaml)为准。SPEC 更新见[独立证据](../../tests/acceptance/initial/G5-spec-update/evidence.json)，回执恢复见[独立证据](../../tests/acceptance/initial/G7-verification-resume/evidence.json)，版号括注影响见[五项原生证据重评](../../tests/acceptance/initial/v1-label-reassessment/evidence.json)。固定输入和接受边界见[隔离验收方案](agent-acceptance.md)。

较早的局部程序检查 `30608175d9f5`：15 项通过。它保留未知格式、未知目录、原始数据与 Git 排除文件保护；删除了一项仅检查退役入口名称的测试。因此上表完整套件的计数是对应既有运行当时的结果，不冒充本次重新运行了全套。对齐草稿首轮因猜测一个不存在的参考文件而未通过执行检查；原错误保留，按现有索引完成有限复核后由独立原生会话判定通过。

维护场景 `G9` 已完成实际未收口阻断、停止证据恢复、程序/Skill切换及新会话显式加载，原记录与业务输出保全；见[维护证据](../../tests/acceptance/initial/G9-maintenance/evidence.json)。源与目标均为当前 v1 格式，不进行格式迁移。原生步骤只执行一次；两项外层包装器判断错误及纠正记录一并保留。

历史与整体进度场景 `G8` 的两项原生验收通过，数据表、业务源码与集成HEAD保持不变。真实失败命令仅执行一次，未运行记录有明确限制，取消事实和缺失原输出分别呈现；原输出字节已另行保全。见[历史证据](../../tests/acceptance/initial/G8-history/evidence.json)。

实现评价先落地了产品、领域和目标架构三个读取模块，共 9 项归属文件；见[独立评价绑定](../../tests/acceptance/initial/implementation-assessment/authority-readers/evaluation-binding.json)。这些是代码职责评价，工程材料继续保持草稿；不构成 Git 采用、完整 Agent 效果或负责人接受。

已知 Agent 拒绝修复曾完成三模块有限重核。当前 v1 清理后涉及的两模块和 12 条关系已完成[当前差异复核](../../tests/acceptance/initial/implementation-assessment/current-contract-cleanup/evaluation-binding.json)，原评价、位置变化和新的评价均保留。
初始范围、设计取舍与交付边界见[基线设计](initial-baseline-design.md)；14 轮机器检查及原始失败见[证据索引](../../tests/acceptance/initial/machine-checks/index.json)。复杂流程的原生前置候选和独立拒绝结论见[停止记录](../../tests/acceptance/initial/G4-G2-stopped/index.json)，17 项后续待验没有改记为通过。
本轮已知 Agent 入口拒绝修复及原始证据见[修复索引](../../tests/acceptance/initial/known-agent-guard-change/index.json)。定点回归 `30b2d951c8f4` 为 69 项通过，修复后无进程探针 `737a1374cf49` 确认拒绝，Skill 同步 `a51188c03009` 通过，新 clean wheel `cedc8d6f6c55`、隔离安装 `8c6342d8bbab` 和字节登记 `f68fa067ebbd` 通过。观察准备首次因控制器误用带仓库身份的摘要键而失败，修正后 `03f9c0119538` 通过；原 `42db14333e21` 保留。未重复全部功能套件，未把原 33 项证据改记为新候选通过。

2026-09-29，前两次原生调用因个人额度耗尽而结束；错误和冻结输入保留于[额度记录](../../tests/acceptance/initial/native-quota-block/index.json)。恢复后原会话虽产生新结构化候选，仍附带旧额度错误；同账号同模型的新会话可用性检查673d4f50190b成功。当前已改用新会话，旧错误不改记为通过。

安装验收中配置文件名断言已修正，并在首次与重复安装后检查实际 `strixnova-project.yaml` 和业务数据库均未创建；同一 wheel 的新隔离检查 `f49bec4d8ab7` 通过。只读新产物检查 `3a9622ff6bd2` 确认 Authority 格式 1、两个实际事项、43 个安装合同，原文件不变；初始 intake 不要求数据库包含尚未形成的公共候选 schema ID，原控制器假设错误 `3e8f15e1dc88` 保留。

当前文档检查 `cf808a32e5d0` 覆盖 90 份 Markdown 和 626 个本地文件链接，未发现缺失或跨出仓库的目标；没有验证网页、标题锚点或代码块示例。交付要求逐项边界见[交付要求与证据](delivery-requirements.md)。
当前合同清理见[原始差异与证据](../../tests/acceptance/initial/current-contract-cleanup/index.json)：a550d2d8a214为1失败1通过，5bba08870241为51通过；新构建252fa58d28ad、隔离安装131734e155c7与字节登记2bd4afd98719均通过。对应原模块与关系评价在changed-inputs.json中保留，当前差异复核 242a3dda0dbf 已完成并登记。
首批关系的原生评价 ffa584a85911 已通过独立复核，随后由当前合同差异复核更新引用。约束新会话 2467d742430e 因流中断和错误目录拼写未通过执行检查，没有计为通过。

2026-09-29 此前登记检查 `46bf438dbc0e`：33 项已评价目标和 135 项归属通过既有结构检查；Agent 目录为 30 项有效、3 项需重验、17 项待验，`acceptance_complete=false`。见[原始检查记录](../../tests/acceptance/initial/current-evidence-registration-check/evidence/acceptance-currentness.json)。

16 项旧证据的独立复核已经结束：[沟通与方法](../../tests/acceptance/initial/current-communication-reassessment/evidence.json)中 8 项可复用、3 项需当前政策下实际重验；[状态与恢复](../../tests/acceptance/initial/current-stateful-reassessment/evidence.json)中 5 项可复用。原运行程序、wheel、Skill 和失败历史全部保留；变化源码按原摘要从登记 wheel 保全，当前六文件另外作为差异复核输入监测，不把旧执行改称新执行。

原复核包装器误把 `behavior_replayed=false` 这个预期执行事实放入必须全部为真的 `machine_checks`，导致汇总显示 `checks_failed`。原报告保持不变；使用既有 `report_from_receipt` 对相同回执与冻结材料重新生成机械汇总，将该事实单列。原生结论、理由、问题、引用和行为要求逐字段未变，3 项 `needs_revision` 仍待实际重验。两个证据目录均保存 `mechanical-summary-correction.json`；此纠正不是新语义裁决。

此前工程登记检查 `231d76761f9d`：51 项已评价目标、135 项归属通过既有 Schema；Agent 目录仍为 30 项有效、3 项需重验、17 项待验。见[原始检查](../../tests/acceptance/initial/engineering-progress-checks/231d76761f9d/evidence/record-shape-check.json)。
第二批 12 条关系及首批 6 条约束的当前评价已经登记，原始评价、独立复核和输入身份分别见[关系评价](../../tests/acceptance/initial/implementation-assessment/relations-2/evaluation-binding.json)与[约束评价](../../tests/acceptance/initial/implementation-assessment/constraints-1/evaluation-binding.json)。小修复随后完成新的实际执行和三项独立复核，已按实际运行依赖登记。

当前策略小修复的原运行 `2483035613fc` 未通过：未恢复的临时文件读取错误使驱动未观察确认终点并发送泛化续行，Agent 将其当成方案接受，随后实施了代码。独立原生诊断 `3d1588a95fce` 判定 `needs_revision`，同时指出 Agent 与驱动问题；原始运行、控制器、实际状态和诊断见[失败保全](../../tests/acceptance/initial/current-policy-g1-stopped/index.json)。既有 G1 确认阶段现使用 `max_continuations=0`；新的夹具已实际执行固定进度提问并完成全部门槛、本地交付和三项独立复核；见[新的完整执行证据](../../tests/acceptance/initial/G1-current-confirmation/evidence.json)。通过依据是实际执行与独立复核，原越界失败保持原记录。

最新制品命名检查先在归档诊断脚本的旧名匹配规则中命中一处（`11b66d636b54`）。原脚本按原 SHA 保全到忽略目录，交付目录保存摘要及来源记录，原失败结果未改写。随后 `88b9d0f5b405` 检查该时点 2676 个交付文件、18 个压缩包及 1336 个成员，并显式核对当前 f71 wheel 与离线 ZIP，未再命中。见[命名检查与边界](../../tests/acceptance/initial/current-candidate-namespace/index.json)。后续新增证据仍需最终交付检查，不把本次扫描扩大到未来文件。

第三批 12 条关系的首次独立复核 `21d44c6c8f32` 为 1 项通过、11 项需修订，关键实现未读充分；随后按具体缺口补读，`9cef927e16d9` 通过独立复核并登记。合同与判断标准未减弱，首轮未通过完整保留。

此前工程登记检查 `7a8aa0d59ccd`：81 项已评价目标、135 项归属通过既有 Schema；Agent 目录仍为 30 项有效、3 项需重验、17 项待验。见[原始检查](../../tests/acceptance/initial/engineering-progress-checks/7a8aa0d59ccd/evidence/record-shape-check.json)。
本次同步的评价、独立复核与输入身份见：[relations-3](../../tests/acceptance/initial/implementation-assessment/relations-3/evaluation-binding.json)、[relations-4](../../tests/acceptance/initial/implementation-assessment/relations-4/evaluation-binding.json)、[constraints-2](../../tests/acceptance/initial/implementation-assessment/constraints-2/evaluation-binding.json)。它们不替代整体 Agent 场景或负责人接受。

此前工程登记检查 `a94a33995c36`：81 项已评价目标、135 项归属通过既有 Schema；Agent 目录仍为 33 项有效、0 项需重验、17 项待验。见[原始检查](../../tests/acceptance/initial/engineering-progress-checks/a94a33995c36/evidence/record-shape-check.json)。

2026-09-29 当前复杂场景已复用完成 G1 的夹具：只读澄清阶段保持文档、事项版本、业务源码和 Git 边界；形成候选与第五批关系引用纠正随后遇到同账号额度限制，未取得有效新通过。原生错误估计 04:00 UTC 恢复，现场及原始错误保留于[本轮额度检查点](../../tests/acceptance/initial/current-formation-quota/index.json)。不切换账号或模型绕过额度。

本轮离线检查 `78741d1daa79` 覆盖 90 份文档、644 个本地文件链接，未发现缺失或越界；`07b5e26f098e` 覆盖该时点 3154 个交付文件、19 个压缩包和 1476 个成员，并显式核对当前 wheel/离线 ZIP，无旧名称命中。只证明各自声明范围和时点，后续材料仍需最终检查。

当前复杂形成的独立复核 `ad05a852e65c` 认可 7 项内容行为，但 `GF-CONCRETE-INCOMPLETE` 与四类权威候选就绪关口均为 `needs_revision`。作者未先登记具体事项，且四类候选仅存在于约 67 KB 宿主文档，仓库 17 份既有模型文件未变。原始产物、文件比较与逐项结论见[当前形成记录](../../tests/acceptance/initial/G4-current-formation-review/index.json)。后续补登记不能抹去首次路由缺口；本轮没有投递接受输入。

此前工程登记检查 `1b7b872df406`：93 项已评价目标、135 项归属通过既有 Schema；Agent 目录仍为 33 项有效、0 项需重验、17 项待验。见[原始检查](../../tests/acceptance/initial/engineering-progress-checks/1b7b872df406/evidence/record-shape-check.json)。
本次同步的评价、独立复核与输入身份见：[relations-5](../../tests/acceptance/initial/implementation-assessment/relations-5/evaluation-binding.json)。它们不替代整体 Agent 场景或负责人接受。

此前工程登记检查 `be7793342e34`：105 项已评价目标、135 项归属通过既有 Schema；Agent 目录仍为 33 项有效、0 项需重验、17 项待验。见[原始检查](../../tests/acceptance/initial/engineering-progress-checks/be7793342e34/evidence/record-shape-check.json)。
本次同步的评价、独立复核与输入身份见：[relations-6](../../tests/acceptance/initial/implementation-assessment/relations-6/evaluation-binding.json)。它们不替代整体 Agent 场景或负责人接受。

当前实际文件补齐运行 `e3ac64b37b84` 保持业务源码、测试和 Git 不变，写入四类权威根文件并登记两个事项；独立复核 `fca48acdf6d8` 通过当前候选文件内容就绪关口，同时继续保留首次 `GF-CONCRETE-INCOMPLETE` 未通过。公开查询显示两个事项仍为 `submit_direction`，因此内容就绪不等于已经到达权威接受动作；当前只在既有流程内纠正方向与后续工程方案的顺序，没有投递任何接受输入。

限定纠正后，四类根文件已实际写入并登记两个事项，候选内容通过 `fca48acdf6d8` 独立就绪检查。随后 `086c1aa9c7ab` 按公开流程把两个事项推进到等待方向确认，保持业务代码与 Git 不变；原首次漏登记保留。原始记录见[已补齐候选与方向位置](../../tests/acceptance/initial/G4-current-corrected-candidates/index.json)。当前没有投递任何方向或权威接受输入。

此前工程登记检查 `7a924784dd58`：116 项已评价目标、135 项归属通过既有 Schema；Agent 目录仍为 33 项有效、0 项需重验、17 项待验。见[原始检查](../../tests/acceptance/initial/engineering-progress-checks/7a924784dd58/evidence/record-shape-check.json)。
本次同步的评价、独立复核与输入身份见：[relations-7](../../tests/acceptance/initial/implementation-assessment/relations-7/evaluation-binding.json)。它们不替代整体 Agent 场景或负责人接受。

2026-09-29 05:02 UTC，第三批约束评价与复杂事项工程方案调用均因同账号个人额度结束，服务提示约 09:00 UTC（北京时间 17:00）恢复。原错误及实际公开状态见[工程方案额度检查点](../../tests/acceptance/initial/current-plan-quota/index.json)。撤回事项方向已接受、版本 4，周报仍版本 3 等待方向确认；原作者文字“同意两个方向”与实际限定范围不符，周报没有被确认。恢复时只续作已经授权的撤回工程评估，不重发接受，也不扩大到周报。

此前工程登记检查 `decbf4ddd875`：122 项已评价目标、135 项归属通过既有 Schema；Agent 目录仍为 40 项有效、0 项需重验、10 项待验。见[原始检查](../../tests/acceptance/initial/engineering-progress-checks/decbf4ddd875/evidence/record-shape-check.json)。
本次同步的评价、独立复核与输入身份见：[constraints-3](../../tests/acceptance/initial/implementation-assessment/constraints-3/evaluation-binding.json)。它们不替代整体 Agent 场景或负责人接受。

2026-09-29 17:00 后恢复原生执行：首次续接在15分钟时限结束，实际工具与原始拒绝完整保留；同一会话的一次有限续接成功提交工程方案，业务源码、Git 与周报方向不变。见[当前方案提交记录](../../tests/acceptance/initial/current-plan-submission/index.json)。7项形成内容的既有通过已登记，见[逐项原生结论及失败保留](../../tests/acceptance/initial/G4-current-formation-content/evidence.json)；当前总计40项有效、10项待验，不代表完整候选验收。

此前工程登记检查 `37fa53c18e1f`：128 项已评价目标、135 项归属通过既有 Schema；Agent 目录仍为 40 项有效、0 项需重验、10 项待验。见[原始检查](../../tests/acceptance/initial/engineering-progress-checks/37fa53c18e1f/evidence/record-shape-check.json)。
本次同步的评价、独立复核与输入身份见：[constraints-4](../../tests/acceptance/initial/implementation-assessment/constraints-4/evaluation-binding.json)。它们不替代整体 Agent 场景或负责人接受。
当前复杂工程方案的独立内容复核通过，见[原始方案、拒绝历史及精确投递门槛](../../tests/acceptance/initial/current-plan-review/index.json)。后续测试接受仍须核对当前事项版本和候选指纹；本次复核不代表已完成上游权威确认、业务实施或真人接受。

最新工程登记检查 `f36a95212bd3`：137 项已评价目标、135 项归属通过既有 Schema；Agent 目录仍为 40 项有效、0 项需重验、10 项待验。见[原始检查](../../tests/acceptance/initial/engineering-progress-checks/f36a95212bd3/evidence/record-shape-check.json)。
本次同步的评价、独立复核与输入身份见：[constraints-final](../../tests/acceptance/initial/implementation-assessment/constraints-final/evaluation-binding.json)。它们不替代整体 Agent 场景或负责人接受。

2026-09-29 当前复杂流程保存了真实展示拒绝、重规划、结构修正及一个精确版本引用修复；见[完整纠正记录](../../tests/acceptance/initial/current-governance-corrections/index.json)。最终机械核对0dc83f86f62a已能完整读取四类候选，早先根索引诊断70268f3e5306不代表展开后的完整候选；原控制器读取错误和修正均保留。当前新方案指纹886cc7bb…仍未接受，不复用旧方案指纹10ed0900…的接受。

当前v3独立复核的两项原生结论均为needs_revision，见[具体问题与原始回执](../../tests/acceptance/initial/current-v3-review-findings/index.json)。两项都保留上游引用不一致问题，方案另有编码前四份底账安排缺口。原汇总器把待审候选文件误标为输入材料，已仅纠正来源角色后重新绑定同一原生回执；原文、摘要、理由、问题、结论及引用坐标均未变，不是重新语义裁决或新增调用。

2026-09-29 18:52 原生服务再次返回个人额度限制，估计北京时间22:00恢复。本轮17:00后共发起15次原生调用，其中14次有实际执行或复核，最后1次在任何工具步骤前被额度拒绝；这不是计费额度换算。全部137项工程目标已有评价，其中136项已实现、1项保留符号链接运行证据缺口；Agent目录40项当前有效、10项待验，7条工程保障尚未评价。原始服务错误、未变现场和恢复位置见[本轮额度阻断](../../tests/acceptance/initial/evening-quota-block/index.json)。不得沿用旧方案接受或把测试接受当成真实仓库交付授权。

22:20后已实际恢复原生服务，但十分钟修正与三分钟收口均未形成可投递的新方案；见[实际执行与停止位置](../../tests/acceptance/initial/late-plan-attempt/index.json)。工作树status给出unadopted_project提示，create_project提交又被既有调查Git版本拒绝，相关原文保留；不能把超时或状态矛盾说成验收通过。当前没有新额度错误，首次登记定点复验在独立副本中进行。

独立首次登记复验0d114775019b中，原生作者完成读取后明确表示回答关键事实前不登记；实际事项数为0，源码和Git未变。该定点场景停止，未启动独立通过复核，原失败不改写；见[复验记录及初态边界](../../tests/acceptance/initial/first-intake-recheck-stopped/index.json)。
