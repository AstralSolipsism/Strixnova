# Coding Agent（智能编码代理）命令手册

> 适用版本：Strixnova 0.1.0.dev0
> 原则：先读最小 CurrentAction，再提交它要求的一类输入；不要自行编排状态机。

## 1. 入口不是一大套命令教学

当前输入使用 Direction v5、EngineeringAssessment v8、EngineeringPlan v9 和 ActualResult v5。实际结果须携带复核前从 engineering.review_subject 取得的 review_subject_ref，内容变化后重新复核；该身份不证明语义正确。新增逐项核验安排及结果，以及实际结果内的延期条目和精确后续处置；`strixnova status --follow-ups` 独立查询已接受的跟进记录。示例与边界见[逐项核验与延期跟进](逐项核验与延期跟进.md)，精确字段以同版公开输入合同为准。

尚无 Strixnova 时，先按[安装与首次使用](installation-and-first-use.md)运行离线包入口；已有 Windows x64、Python 3.12 和 Git 是前提，不需要维护者提供它们的安装程序。后续命令中的 `strixnova` 指安装返回的精确 `runtime.entrypoint`，先核对再使用，避免调用同名旧安装。

安装 Python 包后，如果宿主尚未直接加载安装包内的精确 Strixnova Skill（技能），先运行一次：

```powershell
strixnova setup-agent
```

它只把随包提供的 `strixnova` Skill 复制到 `CODEX_HOME/skills` 或 `~/.codex/skills`，不修改 Agent 配置，不安装 hook、插件、凭证或会话管理。目标已有不同内容时会停止；只有显式 `--replace` 才先备份再替换。也可以用 `--skills-dir <dir>` 指定其他 Agent 的 skills 根目录。

Skill 是受支持代理工作流的必要渐进说明入口。`setup-agent` 只是安装它的一种方式；宿主已经能从安装包直接加载精确 Skill 时无需重复复制。Skill 只在用户明确要求使用 Strixnova 或继续已有 WorkItem 时触发，不是用户授权、语义权威、身份认证或第二套状态机。Agent 的代码搜索、工具选择、上下文组织和 subagent 使用不属于 Strixnova 管理范围。

## 2. 七个普通事项入口与六个独立入口

| 意图 | 作用 |
|---|---|
| `intake` | 根据用户原始请求创建 WorkItem，不扫描代码、不建 Git 分支 |
| `next` | 读取最小下一步，必要时再取当前动作列出的单项记录 |
| `submit` | 提交方向、工程评估、重规划、目标前进或冲突判断 |
| `confirm` | 记录方向、完整工程方案、实际结果三个用户确认之一 |
| `delivery` | 建立工作区、展示实际结果、记录提交、本地合入和安全清理 |
| `verify` | 运行已确认命令、记录 not_run，或提交运行后的重测判断 |
| `cancel` | 取消事项，或处理保留、转移、丢弃未合入工作 |

另有以下不应伪装成普通 CurrentAction（当前动作）输入的入口：

| 入口 | 作用 |
|---|---|
| `status` | 只读查看已采用项目权威；`--working-tree` 只检查未提交候选，不采用文件 |
| `context` | 检查明确项目范围、读取原字节；`context review` 按改动或模块准备审阅资料，不创建事项、不执行审阅 |
| `authority` | 记录上游长期权威候选展示、读取完整复核包，并一次提交完整有序决定数组 |
| `activity` | 记录发布、部署、回滚等外部活动计划、授权状态和真实回执；不执行外部活动 |
| `alignment` | 在当前已确认实施切片内准备实现观察、条件式执行计划内 provider，并恢复性写入实现对齐草稿；不推进事项、不确认或采用候选 |
| `history` | 独立查询进行中、已完成、已取消事项的历史结果、决定、验证与原版本产物；不依赖当前动作 |
| `upgrade` | 对指定项目的 Strixnova 自身程序、Skill 与数据进行显式预检、维护、安装切换、试读及恢复；不执行业务系统运维 |

历史分页、证据可用性、维护切换与停止证据的具体用法见[历史查询与自身维护](历史查询与自身升级.md)。未收口执行持续阻断不安全维护；外部停止依据必须绑定具体操作。

审阅资料的输入合同、两种范围、版本选择及缺口处理见[审阅上下文只读查询](审阅上下文只读查询.md)。先读取 `strixnova context contract review`；资料可用不等于审阅通过，旧观察和未确认材料不能冒充当前实现或已采用规则。

`authority` 不带 `--input` 和 `--authority-kind` 时只读取完整复核包；带
`--authority-kind` 时会记录一次精确候选展示并推进事项版本，但不会写项目权威文件；
带 `--input` 时必须一次提交当前确认包中的完整有序 `decisions`（决定）数组，不能逐项提交。

`activity` 的 `authorize` 记录已有授权：Agent 先确认负责人已有授权明确覆盖该外部活动，沿用仍有效的授权，不重复请求；本地实际结果接受本身不授权发布或部署。

外部活动处于 `planned` 时可通过 `action=cancel` 取消计划。进入 `authorized` 后，如果外部系统确认活动在执行前取消，使用 `action=record` 提交 `event_kind=canceled` 的真实回执，可直接进入 `canceled`，无需先记录 `started`。运行中取消也使用真实取消回执；只有取消意图或执行情况未知时，先核对外部事实。回执保留计划中的外部系统身份、来源、原始证据引用和剩余影响。

成功的结构化业务命令输出一行 JSON；调用方必须按 JSON 解析，非 ASCII 输出会使用 `\uXXXX` 转义以跨越 Windows 控制台、管道和宿主捕获编码。帮助、版本与参数解析错误遵循 CLI 文本格式，`upgrade run` 原样转发所选入口。输入统一使用内联 JSON、`@文件` 或 `@-` 标准输入。PowerShell 下包含中文等非 ASCII 内容时，优先使用明确保存为 UTF-8 的 `@文件`；只有调用方能保证标准输入是 UTF-8 字节时才使用 `@-`，纯 ASCII JSON 也可用 `\uXXXX` 表示非 ASCII 字符。不要让 shell 代码页把语义落成问号。

普通事项除 `intake` 和只读 `next` 外，写命令形状固定：

```text
strixnova <submit|confirm|delivery|verify|cancel> \
  --work-item-id <ID> --version <work_item_version> --input @-
```

`--version` 是防止同一事项并发覆盖的整数版本，不是凭证或租约。写入成功会直接返回新的 `next`；不要紧接着重复读取同一状态。

### 2.1 只读检查、授权执行与安全隔离不是一回事

`next`、普通 `status` 以及长期权威只读投影不会运行项目代码、项目 Git hook、项目自定义转换或远程操作；版本库对象读取会禁止延迟远程获取，无法在旧 Git 的部分克隆中保证这一点时直接拒绝。这里的“只读”是对项目代码与项目文件副作用的承诺，不表示机器已经理解文档语义。

`verify`、构建、结果提交和本地合入则是项目负责人通过已确认方案授权的本地执行。它们以当前宿主用户权限运行，验证命令、构建工具或本地 Git hook 都可能执行项目代码。Strixnova 负责校验计划、顺序、范围和回执，但不提供针对恶意仓库、恶意命令、恶意本地用户或恶意已授权代理的安全沙箱、宿主身份认证或多用户隔离；需要运行不可信项目时，应另用操作系统、容器或虚拟机隔离。

## 3. 开始与恢复

创建事项：

```powershell
strixnova intake --input @-
```

```json
{"title":"简短标题","request":"用户原始请求，不添加未确认范围"}
```

断线恢复时，先列出未完成事项：

```powershell
strixnova next
```

处理已知事项：

```powershell
strixnova next --work-item-id <ID>
```

聚焦结果会附带当前事项的 `relations.declared` 和 `relations.referenced_by`。默认 `strixnova next` 只用于恢复未完成事项，不展开关系理由。不要为了寻找一个不明确的关系目标扫描全部 Authority 历史；用户和当前项目事实没有明确目标时就不声明关系。

每次写入前，必须先读取 `input_contract_ref` 指向的公开输入合同。它给出当前动作的精确命令、输入载荷结构、引用结构和纠偏规则，是字段结构的唯一公开依据；不得搜索已安装包源码、内部结构契约或测试夹具猜字段。可在同一次 `next` 调用中把该合同与已经明确需要、且不依赖本次响应的其他记录一起读取。

只读取 `record_refs` 中当前判断确实需要的正文。若两个或更多引用已经
明确、都确实需要，且彼此不依赖本次响应，可在一次调用中重复
`--record`：

```powershell
strixnova next --work-item-id <ID> --record engineering.plan
strixnova next --work-item-id <ID> --record direction --record direction_confirmation --record project.engineering
strixnova next --work-item-id <ID> --record input.contract:submit_direction --record request --record project.direction_context
```

聚焦读取默认采用完整响应字节预算。大值返回可继续读取的目录或页，按返回的子引用、游标和
来源身份续读，具体见[当前行动材料有界读取](当前行动材料有界读取.md)。不要将目录、未展开值
或宿主截断输出当作完整的写入合同。

如果下一条引用要根据本次返回内容才能确定，就在收到返回后再读取；不要
为了减少命令数而预加载列表中的全部记录。

WorkItem 完成后 `CurrentAction` 会变成 null，但仍可按需读取两种只读工程追溯：

```powershell
strixnova next --work-item-id <ID> --record engineering.trace.current
strixnova next --work-item-id <ID> --record engineering.trace.audit
```

`current` 只显示已被项目本地集成提交采用的关系；`audit` 还保留被重规划、取消或替代的历史。两者都由 WorkflowAuthority 与 Git 临时派生，不是新的写权威，也不会在默认 `next` 中展开。

已有正式项目先读取 `project.engineering`，确认工程方法是否已采用或有条件采用。只有当前影响确实需要领域证据时，才读取 `project.domain.catalog`；它只给出 Model 和根 Collection。之后每一层都直接复制上一层返回的 `record_ref`：沿实际相关的 Collection 分支逐层读取，选择一个 Source，再读取需要的 Fact 正文。路由引用会携带下一次直接读取所需的路径，调用方不要自行删减或拼接。需要确定性依赖闭包时读取 `project.domain.closure:<FACT-ID,...>`。已经选定且同一步需要的多个 Fact 正文和闭包可以批量读取；尚未由本次路由返回确定的引用仍留到下一次调用。架构和实现对齐分别读取 `project.architecture` 与 `project.domain.alignment`。不要展开其他 Collection 或 Source，也不要从 Collection 标题猜限界上下文。

验证阶段按 CurrentAction 精确读取
`engineering.plan.verification_commands`；该记录直接给出确认过的命令 ID、
argv、cwd、种类和覆盖目标，不得按位置猜测 `VC-001` 等身份，也不要为了找命令
反复读取完整工程方案。

不要预先加载 Authority（正式事实）历史、所有视图或全部记录。CurrentAction（当前动作）已给出 `action_type`、`actor`、`intent`、`input_kind`、`input_contract_ref`、`record_refs`、`blocking_facts` 和当前版本，足以决定下一步。

## 4. 语义输入由 CurrentAction 决定

`submit` 只接当前 `input_kind` 对应的 payload（输入载荷）；精确结构以 `input_contract_ref` 返回的公开输入合同为准：

- `direction`：目标、范围、非目标、约束、取舍和验收方向，并用 `decision_context` 绑定当前产品决定；如有真实的其他事项目标，可附带 `work_item_relations`；
- `engineering_assessment`：一份完整 `strixnova.engineering-assessment.v1`；
- `replan`：发生变化的具体事实；
- `target_advance_assessment`：Agent 查看原生 Git diff 后判断语义是否受影响；
- `conflict_resolution`：冲突是否改变方向、方案或用户可见结果，以及必须重测的命令。

`direction` 不是把用户第一句话机械拆进六个字段。先读取 `project.direction_context`：它完整给出当前已采用产品目的、阶段、能力目录、非目标和约束，但不做相关性推荐。相关能力由 Agent 选择；每条产品护栏必须由 Agent 说明 `applies`（适用）、`not_applicable`（不适用）或 `reconsider`（建议重开）及理由，并记录重要假设与重开条件。程序只校验当前版本、身份、引用、唯一覆盖和失效，不评价相关性或理由。尚未采用产品权威的新项目使用空上下文，不伪造引用。

随后做比例化澄清：能从项目查明的事实由 Agent 自己调查，只向用户询问会实质改变目标、范围、非目标、约束、取舍或验收的决定；一次只问一个，并给出推荐答案及用户可见影响。请求已经明确时不增加仪式性问题，方向已经足够安全时立即停止讨论。普通对话不逐轮写入 Strixnova，最终只提交一份准备确认的方向；仍有关键决定未解决时提交具体 blocker。产品上下文变化会使旧方向失效；`reconsider` 只触发产品修订评估，既有护栏在新产品定义被确认采用前继续有效。面向用户展示时解释能力、护栏处置和假设的含义，不把内部引用或哈希当成可理解内容。

工程评估由 Coding Agent（智能编码代理）一次性形成并在提交前自检。程序校验结构、真实 SourceReference（来源引用）、关系、操作冲突、项目治理规则和命令格式，然后投影 EngineeringPlan（工程方案）；没有第二份 Strixnova管理的语义复审。缺失语义必须由智能编码代理基于事实补齐，程序不生成模板理由或测试命令。

既有正式项目只需提交不可变 `investigation_ref`；程序会从该 Git 提交确定性定位项目配置和工程基线。除非具体语义主张确实引用其正文，不要再把这两个文件重复包装成 SourceReference。

随包唯一 Skill（技能说明）的分段参考解释如何形成专业语义并路由到公开字段合同。不要为了找到格式遍历源码、测试夹具或猜状态。工程评估用 `direction_ref` 引用当前已确认方向，不再复制目标、范围、约束和验收；`direction_version` 必须取自 CurrentAction（当前动作）允许读取的 `direction_confirmation`，不能用后来已经前进的 WorkItem（工作事项）版本代替。`affected` 与 `unknown` 影响项填写理由和证据，`unaffected` 只列维度名；十二个维度必须恰好各出现一次。风险、方案比较、设计、操作、ADR（架构决定记录）、验证、交付计划和未知项只在有真实内容或适用规则要求时提交，空章节可以省略。没有验证命令时必须填写 `verification_not_required_reason`，不得伪造命令或“低风险”占位内容。正式验证命令是最终证据义务，不得把相互包含的开发反馈命令全部列入，也不得先在 shell（命令环境）手工跑完整矩阵后再由 `strixnova verify mode=run` 重复执行。

工程方法从 ProjectEngineeringPolicy（项目工程政策）读取采用状态，不按请求关键词猜测。已采用或条件采用的方法与受影响或未知维度相交时，Coding Agent（智能编码代理）在方法应用中明确写“已应用”或“考虑后未应用”；应用时列出技术、目标和证据。项目采用变化写入项目工程政策并同步更新 ProjectEngineeringBaseline（项目工程基线）的精确政策引用；领域事实引用和领域事实变化保持独立。每个正式项目都维护 ProjectDomainModel（项目领域模型）和 ProjectImplementationAlignment（项目实现对齐），不以采用 DDD（领域驱动设计）为前提。实现对齐是完整版本化权威；涉及其管理范围时，工程方案必须明确操作完整对齐清单及受影响底账，实际结果用长期产物回执和最终修订闭环。程序只判定结构影响和确定性漂移，不替智能编码代理编写语义结论，不把领域正文或对齐结论塞回项目工程基线。方法判断沿用工程方案确认，不增加确认点，也不直接提高 AssuranceBand（保障等级）。

`work_item_relations` 中每项填写目标 WorkItem ID、关系类型和具体理由。类型只允许 `related_to`（一般关联）、`part_of`（本事项属于目标大事项）、`depends_on`（本事项需要目标成果）、`follows_up`（本事项是目标的后续延续）或 `supersedes`（本事项取代目标旧方案）。优先选择具体类型，只有用户请求或项目事实确实指向已有事项时才填写；不要为了凑关联编造目标。关系随源事项的方向一起确认，只用于追溯，不会继承测试义务，也不会自动阻塞、排期、加锁、合并或解决冲突。

当新事实要求重规划时，只有工程方案变化才直接提交更高 revision 的工程评估；目标、范围、取舍或 WorkItem 关系变化时，先提交一份完整修订方向并重新取得方向确认，再提交修订评估。调查已经足以逐项说明影响、操作、验证和重要未知项时应立即形成评估；剩余不确定性写入 `unknowns_and_limitations`，不要为了理解整个项目继续无界探索。

## 5. 三个用户确认

当 `intent=confirm` 时，先把当前方向、完整工程方案或实际结果解释到用户可以做决定。主动说明当前状态与问题、接受后的变化、产品与用户效果、工程逻辑、主要影响和风险、未知、推荐，以及本次确认授权和不授权什么；按候选复杂度调整篇幅，不套固定标题，不先倾倒字段、文件清单或百分比。然后用一句自然问题请求决定并结束回复，等待用户新的消息。不得在形成、提交或展示候选的同一轮调用 `confirm`。

三个普通关口允许用户自然表达接受或纠正。Agent 结合完整展示及后续答复记录 `agent_decision`（`decision=accept|request_changes` 和 `reason`），用户不填写 `decision_label`、`candidate_fingerprint`、schema 或判断字段。方向确认只授权继续调查和形成方案；方案确认只授权本地实施与验证；实际结果确认只接受已展示的实施与验证事实，并授权本地 Git 交付。三者都不授权远程推送、正式发布或部署。

用户说“没看懂”或提出问题时，继续解释同一候选，不调用 `confirm`，也不改变候选、WorkItem 版本或确认绑定。只有会实质改变候选内容的纠正才按退回处理。用户刚才对澄清问题、推荐方案或业务取舍的回答不等于确认随后形成的完整候选；“认同，执行”可以明确接受刚刚完整展示的候选，不因措辞或标点要求重答。含修改条件不能接受原候选，指向不清时先澄清。只有用户在后续消息中明确接受或退回当前候选后才能提交：

```json
{
  "candidate_fingerprint":"由 Agent 从当前动作机械复制的内部候选绑定",
  "user_confirmation":"逐字复制用户后续的整条新消息",
  "agent_decision": {
    "decision":"accept",
    "reason":"负责人后续答复明确接受刚才完整展示的当前候选"
  }
}
```

CurrentAction（当前动作）的 `confirmation_challenge`（确认挑战）把完整候选和 WorkItem（工作事项）版本绑定为内部指纹，由 Agent 判断用户后续答复是否明确接受，程序不识别自然语言意图。Agent 提交时从同一当前动作机械复制内部指纹；`user_confirmation`（用户确认原文）必须逐字来自随后新的用户消息，不得自行拼造、改写或复用旧答复。程序用指纹阻断过期或被替换候选，但不把它冒充用户理解、身份认证、说明质量或候选语义正确的证明。新的 `agent_decision` 保存 Agent 对当前候选的解释，不作为机器证明；含修改条件、指向不清或仅提出问题时，不得接受原候选。历史固定文字记录按原合同读取。

Strixnova根据 CurrentAction（当前动作）判断这是哪个确认点，不要求 Agent（智能编码代理）再传内部种类。Agent（智能编码代理）不得代替用户确认，不得从沉默推断接受，也不得复用更早的澄清答复或旧确认。

## 6. 实施、验证和完成

开始正式实施时，`delivery` 输入本地目标分支和可选策略：

```json
{"target_ref":"main","merge_strategy":"no_ff"}
```

Strixnova 只管理本地 Git。若目标分支晚于评估的 `investigation_ref`，会先要求 Agent 查看原生 diff 并提交语义影响判断；不会保存完整 changed-paths 清单。单事项使用主工作树，并行事项才显式给仓库外 `worktree_path`。

当前实施切片包含 `domain_alignment` 操作时，使用安装态复核与写入入口：

```text
strixnova alignment prepare --work-item-id <ID> --version <N> --input @revision.json
strixnova alignment capture-external --work-item-id <ID> --version <N> --authorize-external --input @capture.json
strixnova alignment inspect --work-item-id <ID> --version <N> --input @inspection.json
strixnova alignment write-candidate --work-item-id <ID> --version <N> --input @candidate.json
```

已有已确认修订的 `revision.json` 只含
`schema_version=strixnova.implementation-alignment-preparation-request.v1`、新
`alignment_revision_id` 和精确 `supersedes_revision_id`；首次建立才增加观察范围、受管源码范围和四份底账路径。第二步仅在 `prepare` 返回
`external_capture_required=true` 且已确认工程方案已有精确 provider 计划时调用，CLI 不接收临时 argv、材料或策略。provider 计划必须绑定程序、入口脚本、配置和支撑文件的 SHA-256，执行前重新核对。`inspection.json` 只保存最终采用的完整 `preparation_ref`；Agent 调用 `inspect` 并沿不透明 `next_cursor` 顺序读取逻辑记录，不读取 `.strixnova/artifacts/implementation-alignment` 的清单、组件或分页实现。程序负责散列、节点、关系、覆盖、回执和引用，要求受管作用域互不重叠，并在写入前复核六个目标文件没有被后续编辑。六文件替换使用持久事务日志，最终校验失败或提交前进程中断都恢复一致旧文件组。

缓存维护不属于上述顺序。只有项目负责人明确要求时，先运行 `strixnova alignment gc --dry-run`；接受返回的 `orphan_set_sha256` 后，才用 `--apply --expected-orphan-set-sha256 <值>` 删除同一批无清单引用的孤立组件。该命令不删除准备、捕获、事务或长期权威。

成功结果仍是 `draft`。`candidate_valid` 只证明结构和交叉引用通过；
`complete_alignment` 还要求完整覆盖、源码对齐、依赖通过、责任已实现且没有偏离和未知；
`semantic_content_machine_proven=false` 明确表示机器没有证明语义。该入口不改变 WorkItem 版本或状态，后续仍按当前验证、ActualResult（实际结果）展示与负责人确认流程推进。

`verify` 只运行工程评估中明确选择的 `command_id`。先 `mode=run`，命令结束后再按下一步以 `mode=assess` 提交 Git 是否又发生相关变化、是否要重测和理由；不能运行时诚实提交 `mode=not_run`。验证汇总只有 `not_required`、`pending`、`passed`、`completed_with_issues` 四种状态，下一步由 CurrentAction 表达。具体 payload 见 Skill 的 `references/verification.md`。

ActualResult 的 `method_application_results` 必须覆盖每个已计划 method use；`realized` 引用真实回执、交付结果或长期产物，`not_realized` 同时披露方法偏差和用户可见限制。未应用的方法不生成假结果。

ActualResult 的 `governance_rule_results` 必须逐条覆盖工程方案中的适用治理规则。`satisfied`（满足）必须引用真实证据且没有未关闭缺口；`partially_satisfied`（部分满足）、`not_satisfied`（不满足）和 `unknown`（未知）必须同时给出缺口、纠偏行动和用户可见限制。`semantic_content_machine_proven`（机器证明语义内容）必须明确为 `false`（否）；内部工程判断不能冒充外部认证或合规。

验证满足后，`delivery` 接收 `strixnova.actual-result.v1`。用户确认实际结果之前不得形成实现提交。确认后由 Agent 显式暂存本事项文件、形成原子提交，再用空对象调用 `delivery`，由 Strixnova 记录提交、本地合入并安全清理。远程 push、pull、fetch、CI 和发布由用户管理。

## 7. 取消

开始取消：

```json
{"reason":"用户的实际原因"}
```

存在未合入工作时必须向用户展示三项真实选择：`preserve`、`transfer`、`discard`。丢弃只有在用户明确确认后才可同时提交 `"confirm_discard":true`。Strixnova 不自动 stash，不删除非自己创建的分支，也不替用户决定遗留工作的归属。

## 8. 错误处理

- `authority_conflict`：版本过期，重新读取该 WorkItem 的 `next` 并按新事实处理；
- `invalid_transition`：调用意图与 CurrentAction 不一致，回到 `next`，不要猜内部状态；
- `unsupported_authority_format`：停止写入并保留原文件；当前程序只接受已声明的精确格式。核对程序与数据来源，不删除数据或伪造格式标记绕过拒绝；当前维护范围见[维护说明](历史查询与自身升级.md)；
- 其他 typed error：修正它指出的输入或真实项目条件，不改数据库、不伪造回执、不绕过 guard。

本期不交付 WebUI。CLI + 随包唯一 Skill 是当前受支持 Coding Agent 接入面；界面将在核心能力稳定后从零重构。
