# Antigravity 自动验收与手动备用入口

验收使用真实 Antigravity CLI，固定 `gemini-3.8-flash-low`。Codex 只准备夹具、实现控制器、收集原始记录及运行确定性检查，不能充当验收 Agent 或语义裁判。完整候选是否完成以[验收目录](../../tests/acceptance/guided-formation-cases.yaml)及其实际证据范围为准，命令退出 0 不等于业务通过。

## 程序、Agent 与负责人各做什么

| 职责 | 执行者 | 能证明什么 |
| --- | --- | --- |
| 固定输入、保存原始输出、核对版本和文件状态、提取引用 | 程序 | 确定性事实及实际效果 |
| 理解原文、识别遗漏和冲突、判断证据是否支持结论 | 独立 Antigravity 会话 | 有范围、有依据的语义审阅意见 |
| 接受实际结果及重要取舍 | 项目负责人 | 本项目适用的正式接受 |

沿用领域不变量和工程政策，不增加语义引擎、产品状态或 ADR。外部开发验收脚本不进入 Strixnova 运行时，也不通过 Strixnova 管理 Strixnova。

审阅输入分开标注 user_input、original_input、author_response、author_artifact、skill_contract。Agent 返回来源身份和起止行号，不再生成 response_quote/evidence_quote。程序核对该引用属于本项允许的输出、范围存在、来源未变后直接附上原文与 SHA-256；不改写 Agent 理由，不通过理由与原文的字面相似度判断理解正确。引用有效也不等于结论成立。

只有测试本身要求精确引用、字节保全或格式一致时才检查对应精确要求。数量、身份和状态由程序直接核验，不让 Agent 重抄后再校对。

## 无交互权限

已移除临时修改用户 settings.json 和逐种命令写法扩充 allowlist 的实现。正式入口在本次 CLI 调用加入 `--dangerously-skip-permissions`；不修改全局配置，不申请 Windows 管理员权限。

该参数自动批准本次进程的工具请求。夹具目录仅用于分开存放输入与产物，**不是经过验证的操作系统沙箱**，不能阻止进程访问目录之外。操作者必须已明确授权这种执行方式；若外层执行环境拒绝，保留阻断，不绕过、不改用 Codex。

此选项只解决 Antigravity 的工具审批，不赋予 Windows/WMI 权限，也不解除外层执行环境限制。依据官方[无交互权限说明](https://www.antigravity.google/docs/cli/headless/#permissions-in-headless-mode)。

## 执行入口

运行前依[隔离验收方案](../engineering/agent-acceptance.md)固定题面、原始输入、场景范围、模型、权限和完成标准，并核对本机实际可用模型。驱动使用 `scripts/agent_acceptance.py`；它分别记录传输完成、工具收口和独立的场景终点，不解释答复语义。场景配置和当前进度以本轮验收登记及[验证状态](../engineering/validation-status.md)为准。

独立审阅通过现有入口执行：

```powershell
.venv\Scripts\python.exe scripts\local_validation.py run --label antigravity-review --keep-workspace --pin -- .venv\Scripts\python.exe scripts\review_antigravity_evidence.py --spec <已登记的审阅规格.json> --output <本轮新的输出目录>
```

spec 列明原标准、证明范围、实际来源文件、允许引用的作者输出及已有机械检查。程序保留原始模型输出，再核对来源、行号和内容摘要；引用有效不等于语义结论成立，不把操作说明当作真实执行。

宿主登录、权限或环境被阻断时，保留原始诊断，由负责人在本机完成必要操作后继续。不得修改全局认证设置、切换 Codex 代验或把未完成会话标为通过。

## 实际效果与失败分类

- 有运行要求的场景：检查真正的文件、状态、命令回执和新旧版本；操作说明或作者自述不代替执行。
- 纯讨论场景：核对实际答复与题面、来源及语义标准，结果仅覆盖讨论范围。
- 合同结构场景：只覆盖实际 Skill 合同，不计为完整工作流。

控制器分别记录 `outcome`、`failure_layer`、`machine_checks`、`reviewer_verdict`。权限拒绝、宿主退出和超时先归入执行环境；观察器或协议解析错误归入验收外壳；实际检查失败但尚无原因时记为 undetermined，不自动判定产品有缺陷。独立审阅者在 issues 内区分 Agent 输出问题、已观察产品行为问题与未知原因。机器通过不会生成语义通过，也不会产生负责人接受。

失败的原始记录保留。修复后另存新记录，不将后来的成功改写成首次通过。仍匹配且范围充分的旧证据可以复用；资料不足则保留待验，不仅刷新指纹。
