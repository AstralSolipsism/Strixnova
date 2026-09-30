# Strixnova

Strixnova 是给非专业项目负责人使用的本地软件工程管理工具，具体命令由 Coding Agent（智能编码代理）执行。

当前源码用于协作开发，接手入口见[协作开发说明](CONTRIBUTING.md)。11 项 Agent 机械负担的产品侧改进已实施，定点程序验证完成；真实 Agent 回归待验，当前源码尚未形成新的发行包。

当前源码版本为 `0.1.0.dev0`（开发候选）。[当前验证状态](docs/engineering/validation-status.md)分别说明源码回归、工程材料、制品安装、Agent 场景和实际结果接受；实现中或待验项目不构成正式可用声明。

前一冻结候选中，首装后首次创建事项的布局误判，以及两条 Git 流程测试遗漏约束核验的问题已修复；最终隔离安装实际完成了首次创建、再次读取和 BDD 报告链路验证。

已记录工作通过独立 `strixnova history` 入口读取；`strixnova upgrade` 维护同一当前数据格式下的程序、配套 Skill 与数据组合。初始 Authority、活动库和证据格式各为 v1。事项修订、格式版本、软件版本和内容摘要分别校验。具体路径与恢复条件见[历史查询与自身维护](docs/使用说明/历史查询与自身升级.md)。

一个项目可以包含多个独立 Git 仓库，以一份事项、整体方向、方案和结果接受管理共同目标。必要输入按仓库及内容限定，整体接受后逐仓交付；部分合入、冲突、取消和重规划保留原事实。没有后端源码时，可使用具有实际版本、契约和环境证据的服务依赖，不能把连通性当作源码覆盖。配置和操作见[多仓库事项与整体方案](docs/使用说明/多仓库事项与整体方案.md)。

## 设计理念

Strixnova 把软件工程方法、流程规范和标准产物分成四层落到项目中。通用依据先进入项目长期规则，再进入当前建设事项，最后由实际执行证据说明做到了什么。每项方法或规范最终都要落成项目规则、计划操作、验证义务或结果证据。

这套设计从模糊想法也能开始。Agent 先调查项目中已经知道的事实，再通过 GuidedFormation（引导式形成）逐步补齐真正会改变结果的决定。想法还不能形成需求或具体建设事项时，Agent 会按当前最大缺口选择界定问题、扩展选项、压测假设、调查证据或归纳产品认识；这五种做法可以跳过、组合或重复，不是必须走完的阶段。信息已经足够时直接起草，核心假设不成立时也可以建议否定或搁置，不强迫用户完成访谈、文档或编码。

规划时再分别判断三件事：需求还要形成到多细、最少需要几个可独立验收的结果、每个结果需要多深的工程保障。三者不会因为文件多、代码少或用了 PRD、Story 等名称就被混成一个“规模等级”。

| 层次 | 在 Strixnova 中的落地形式 | 解决的问题 |
|---|---|---|
| 通用工程依据 | 版本化治理档案，保存规范来源和 Strixnova 自己的工程解释 | 哪些工程主题需要关注，什么影响会触发规则，需要哪些信息和证据 |
| 项目长期规则 | 产品定义、领域模型、目标架构、工程政策、实现对齐和工程基线 | 这个项目准备长期建设成什么样，采用哪些方法和规则，当前实现处在什么位置 |
| 当前建设事项 | Direction（方向）、EngineeringAssessment（工程评估）和 EngineeringPlan（工程方案） | 这次要解决什么，影响什么，怎样拆分、实施、验证和恢复 |
| 实际执行 | 命令回执、ActualResult（实际结果）和本地 Git 历史 | 哪些工作真实执行过，方法怎样落实，结果有哪些偏差和限制 |

### 常见方法、流程和产物的真实状态

这张表回答一个实际问题：当 Agent 说“采用了某种方法”时，Strixnova 到底能留下什么、能阻止什么，还有哪些部分尚未实现。

表中的“正式落地”表示已经有专门的数据结构、状态或证据检查；“等价承载”表示核心内容由 Strixnova 自己的正式产物保存，但不沿用常见文档名称；“部分承载”表示可以复用现有机制，却还缺少该方法独有的规则；“外部衔接”表示 Strixnova 管计划和回执，工作由外部工具完成。字段看起来相似，不算一种方法已经落地。

| 类别 | 常见方法、流程或产物 | 当前程度 | 已经落到项目里的内容 | 尚未做到或明确边界 |
|---|---|---|---|---|
| 产品方法 | 产品发现与想法验证 | 内置按需方法 | 随包 Skill 根据真实缺口选择问题界定、选项扩展、假设压测、证据调查或产品归纳；明确请求可以跳过，想法也可以以搁置、否定、等待实验或只有更清楚认识而结束 | 不管理用户访谈、实验项目或产品组合；Agent 的判断与一次场景测试都不能证明市场需求或商业成功 |
| 产品方法 | UX 形成与审阅 | 内置按需方法 | Agent 从已有需求与设计系统形成关键流程、动作反馈、适用状态和恢复说明；需要时用小原型回答具体交互问题，再按真实来源审阅与交接 | 面向目标产品，不是 Strixnova WebUI；原型与 Agent 推演不构成真人可用性测试，不增加 UX 权威或确认流程 |
| 工程方法 | DDD（领域驱动设计） | 正式落地 | 项目记录采用状态；当前事项记录统一语言、限界上下文、上下文映射和领域不变量追溯怎样使用；实际结果逐项交代是否落实，并连接领域模型、目标架构与实现对齐 | 程序不判断领域含义是否专业正确，也不提供 DDD 成熟度认证 |
| 工程方法 | SDD（规格驱动开发） | 核心做法融入现有流程 | 方向记录行为、范围、约束和验收，工程方案安排实施与核验，正式修订处置下游影响；Agent 按需编写、审阅和更新 SPEC | 当前未单独提供 SDD 方法的采用登记和执行审计；SPEC 使用现有方向与方案的确认，不取得独立写权 |
| 工程方法 | TDD（测试驱动开发） | 按需实施与测试指引，正式方法部分承载 | Agent 在选择接口或测试边界、修复行为、按项目要求测试先行时，使用独立预期、失败反馈和可维护的行为测试；方案绑定最终验证，实际运行形成回执 | 不强制所有工作测试先行，不管理红、绿、重构的逐步状态；没有观察到失败测试时不得宣称已经完成，普通测试流程不能冒充 TDD |
| 工程方法 | BDD / ATDD（行为驱动 / 验收测试驱动） | 例子到结果的核心链路已内置 | 可观察行为变化在方向验收中保存有依据的例子，方案逐例绑定测试或其他核验；真实执行记录原生用例结果，实际结果另交代断言审阅，历史报告保留原字节；例子沿用方向确认 | 不引入 Gherkin、独立 BDD 模式或额外确认；原生测试报告首批适配 pytest / pytest-xdist，其他框架尚未适配；适用性、预期和断言充分性由 Agent 判断，声明输入范围不等于自动发现全部依赖 |
| 项目管理方法 | Agile、Scrum、Kanban | 尚未落地 | WorkItem（建设事项）及其语义关系可以保存工作的来龙去脉 | 没有产品待办、优先级、Sprint、容量、看板、速率或排期；事项关系也不自动调度和阻塞工作 |
| 标准产物 | Product Brief、PRFAQ、PRD | 内置发现、专门编写与阅读规程 | Product Brief 和 PRFAQ 帮助产品发现；Agent 按需形成、整理、审阅或更新 PRD，检查关键行为、质量约束、取舍、重要输入保全及下游就绪，并绑定产品、领域和必要架构的精确来源 | PRD 不取得独立写权或确认；含义变化回到实际权威，来源与覆盖检查不证明内容正确；没有程序生成正文的导出器 |
| 标准产物 | 领域模型 | 正式落地 | ProjectDomainModel 保存有稳定身份的术语、场景、规则、不变量、限界上下文和上下文关系，并支持修订、确认和引用闭合 | 目录名和类名只作为调查线索，程序不会自动把代码命名认定为领域事实 |
| 标准产物 | 架构说明 | 正式落地 | ProjectArchitectureDescription 保存目标模块、职责、公共接口、依赖关系、架构约束、领域事实归属和实施阶段 | 它描述目标架构，不伪装成当前代码快照；当前实现由 ProjectImplementationAlignment 另行记录 |
| 标准产物 | ADR（架构决定记录） | 正式落地，按需使用 | 当架构、接口、数据影响或项目规则触发 ADR 要求时，工程评估须决定创建、更新或不需要；计划、文件身份、状态、正文、关系和实际结果互相核对，合入后由 Git 长期保存 | 不会为每个事项强制生成 ADR；决定内容是否合理仍由 Agent 和项目负责人判断 |
| 标准产物 | SPEC / Tech Spec / API Spec（规格 / 技术方案 / 接口规格） | 专门 SPEC 编写、审阅与更新规程；接口规格部分承载 | Agent 将 DirectionDecision 与 EngineeringPlan 整理为可读 SPEC，保留稳定需求、约束和验收引用，分开行为、方案及实现比较，按真实来源变化更新；无关实施进度不自动改变规格含义 | 没有平行的 SPEC 或 Tech Spec 写合同，也没有覆盖协议、数据结构、错误、兼容和版本策略的完整 API Spec 合同 |
| 工程方法 | 风险行为合同 | 按实际风险使用的 Agent 指引 | 需要时明确接口效果、权限边界、幂等重试、并发冲突、兼容和恢复，并连接实际验证 | 复用项目现有规格与工具；不自建完整 API 标准，不把 mock 或单元测试当作并发、安全认证 |
| 标准产物 | Story、Epic、Initiative | Story 映射现有事项；聚合对象尚未建设 | 一个可独立验收的 Story 对应一个 WorkItem；WorkItem 内部再用 ImplementationSlice 表达实施步骤，多个事项可保存真实追溯关系 | Epic / Initiative 不是一等对象；没有聚合接受、组合进度、排期或自动 Agent 调度 |
| 标准产物 | 逐项核验、测试计划与报告 | 正式落地在方案和结果中 | 为当前事项的每项验收、约束和已识别风险安排命令验证、Agent 审阅、既有证据复用或明确未核验；命令保存真实回执与重测判断，非命令目标逐项记录结论和依据 | 一条命令可以覆盖多项；引用完整和命令通过不证明核验充分或语义正确，未核验内容必须保留限制 |
| 标准产物 | 运行手册与迁移方案 | 部分承载，按需使用 | 运维部署和兼容迁移属于固定影响维度；工程方案可安排相应文件、恢复步骤、验证和交付证据 | 没有名为 Runbook 或 Migration Plan 的独立结构合同和专属生命周期 |
| 工程治理 | 需求、风险、质量、安全与追溯 | 正式落地为治理规则 | 每项正式建设检查十二个影响维度；适用规则决定风险、方案比较、保障强度、信息项和证据义务；实际结果记录满足、部分满足、未满足或未知 | 机器只能检查结构、引用、状态和确定性证据，不能证明需求正确、安全合规或产品质量 |
| 工程治理 | 明确延期承诺与后续处置 | 已实现精确承接与只读查询 | 已接受结果保存延期条目、责任、复查安排和完成标准；后续事项精确关联原问题，在后续结果被接受后更新派生处置，并拒绝过期的并发更新 | 普通限制文字不自动产生义务；业务条件由 Agent 判断，后续事项完成或取消不自动关闭原问题，不提供排期或后台调度 |
| 工程治理 | 多语言实现观察与锚定 | 正式落地，覆盖按语言和配置声明 | 对声明范围记录受管文件、实际字节散列、可观察的导入、引用和项目依赖、覆盖缺口及提供者回执；Agent 再判断文件归属、架构责任和实现状态 | 用途限于实现对齐证据；Agent 自行分析源码，完整项目语义仍需 Agent 判断 |
| 工程流程 | 本地 Git 变更与交付 | 正式落地 | 为建设事项建立或复用工作区，按切片实施和验证，结果确认后再做精确暂存、原子提交、本地合入、冲突复核和安全清理 | 不管理远程分支、推送、Pull Request 或代码托管平台 |
| 工程流程 | 代码评审、Pull Request 与 CI | 内置 Agent 代码复核方法，平台流程未建设 | 用户请求或当前方案要求代码复核时，Agent 按实际比较基点纳入相关提交或工作树变化，分别核对项目规范与确认需求，引用具体代码、测试和影响；已有八视角审查继续处理权威与方案一致性 | 程序不理解代码或裁决审查语义；Agent 复核不等于真人独立评审，当前没有评审人、批准状态、PR 或 CI 平台集成 |
| 工程流程 | 发布、部署、回滚、观测与维护 | 外部衔接 | `strixnova activity` 为外部活动保存计划、负责人、前置条件、成功标准、停止条件、恢复办法、授权、状态和真实回执 | Strixnova 不执行外部活动，也不自建发布、部署或监控平台 |

Strixnova 当前有明确合同和检查的部分包括项目长期权威、DDD 方法链、事项评估与方案、逐项核验、明确延期承诺的后续处置，以及本地 Git 交付。规格驱动的核心做法已融入现有流程，实施测试和代码复核已有按需 Agent 指引；这些能力不自动表示受管项目正式采用了 SDD、TDD 或 BDD。敏捷排期、真人独立代码评审、PR 和 CI 平台集成仍是明确缺口。

这里的 SDD 指 Spec-Driven Development（规格驱动开发）。规格驱动的核心做法已融入方向、工程方案、实施、验证和变更流程，并提供 SPEC 编写与审阅指引。正式要求仍由现有权威承载，SPEC 由 Agent 依据精确来源形成和更新；当前未单独提供 SDD 方法的采用登记和执行审计。如果指 Software Design Description（软件设计说明），目标架构和工程方案可以承载其中一部分内容，目前没有名为 SDD 的独立文档合同。

内置的[通用治理档案](strixnova/src/strixnova/resources/governance-profile-v1.json)覆盖需求与验收、生命周期与配置、产品质量、测试、架构与长期决定、安全开发、发布运维与维护。当前依据包括 ISO/IEC/IEEE 12207、29148、42010、15289 和 29119-2、ISO/IEC 25010、NIST SP 800-218，以及 Eric Evans 的 DDD Reference。治理档案保存来源信息和 Strixnova 独立编写的工程解释，当前事项只读取与实际影响有关的规则摘要。这些内容用于内部工程评估，引用标准不等于取得相应认证。

工程方法沿同一条链路落地。现行治理档案显式登记的方法是 DDD（领域驱动设计）：项目工程政策先以已采用、有条件采用、未采用或尚未评估记录状态和条件；当前事项再说明使用哪些技术、作用于哪些领域事实以及需要什么证据；实际结果记录方法是否真正落实及其偏差。方法名称本身不会增加流程步骤或自动提高保障等级。

普通 WorkItem 的状态推进由 CurrentAction（当前动作）和版本控制，写入绑定已经确认的上游版本；独立查询等入口遵循各自合同。步骤越级、旧版本写入、前置依赖未满足、必需核验安排或回执缺失时，会阻断对应推进。已经明确记录的失败、未运行或未核验内容，可以在满足适用项目规则并保留限制后进入实际结果确认，由负责人决定是否接受；它们不会因此被记为通过。命令执行结果与 Agent 的语义判断分别展示。

普通 WorkItem 的三类常规确认是方向、完整工程方案和实际结果。首次建立或实质修订产品定义、领域模型、目标架构和工程政策时，项目负责人还要分别决定这些长期内容；取消、明确授权的外部执行和冲突后的重新确认只在实际触发时出现。

项目首次接入的正式仓库交付需要建立配置、工程基线和五类长期权威。Agent 调查并复用已有资料，按项目规模形成完整内容，负责人处理产品含义和重大取舍。后续小改动沿用有效资料，只更新受影响部分；PRD、SPEC 等阅读产物按需形成。

每项正式建设都要完整检查用户行为、产品范围、领域、架构、接口、数据、安全与隐私、质量与性能、部署运维、兼容迁移、测试和文档支持十二个影响维度。受影响和仍未知的部分需要理由与证据，确认无影响的部分只记录结论。保障强度由实际影响和项目规则决定。ADR、方案比较、迁移说明、运行手册和更广回归只在相应影响或规则需要时出现。

方向、工程评估、工程方案和实际结果属于单项建设。下面六类材料会在事项完成后继续留在项目中。

### 项目长期材料

这些材料保存在普通 Git 文件中，每类材料只回答自己的问题：

| 项目材料 | 回答的问题 |
|---|---|
| ProjectProductDefinition（项目产品定义） | 这个产品为谁解决什么问题，承诺哪些能力，哪些内容不在范围内 |
| ProjectDomainModel（项目领域模型） | 业务世界中有哪些稳定概念、规则、关系和场景 |
| ProjectArchitectureDescription（项目架构描述） | 项目准备建设成哪些模块，责任怎样划分，接口和依赖怎样组织 |
| ProjectImplementationAlignment（项目实现对齐） | 当前代码与目标相比已经实现什么，哪里偏离、缺失或仍然未知 |
| ProjectEngineeringPolicy（项目工程政策） | 项目采用哪些工程方法、保障要求、验证和交付规则 |
| ProjectEngineeringBaseline（项目工程基线） | 当前采用的是上述材料的哪些精确修订，处于什么阶段，何时需要复核 |

六类材料通过精确修订互相关联，各自保留自己的职责。正文保存在各自文件中，项目工程基线记录采用的精确修订和复核状态；其他长期产物继续由 Git 管理。产品、领域和目标架构以负责人确认的内容为准；当前代码、测试和历史文档是调查与实现证据。测试结果说明代码经过了哪些验证，领域含义仍以领域模型和负责人决定为准。

上游内容发生变化时，Strixnova 会把受影响的下游材料送回复核。对于实现对齐，未归属的受管文件、未分类或违反目标架构的实现关系、观察覆盖缺口、实现偏离和未解决项会阻止候选声称完整对齐。WorkItem 之间的语义关系用于追溯，不会自行排期或自动阻塞其他事项。

## 项目负责人怎样使用

可以直接要求“把这些资料整理成可以讨论决定的 PRD”“根据这版方向和方案整理 SPEC”，或“只审阅这份 PRD，指出会影响立项的问题”。信息充分时 Agent 直接整理；仍缺重要决定时先调查，再逐项说明建议和取舍。阅读版标明已确认、候选和未知内容，修改含义仍进入原有权威流程，单纯改善表达不会改写来源。

使用时，你先用平常的话说明希望项目发生什么变化。说得清楚时，Agent 调查后直接整理方向；只有客户、问题、边界、重大取舍或成功判断确实不清楚时，才逐项和你补齐。Agent 会判断这是一项可独立验收的工作、多个共享目标的工作，还是需要先形成项目级产品或架构决定，再据此建立工程方案、实施并运行验证。Strixnova 记录其中的决定、版本、依赖和执行结果，并协助 Agent 完成本地 Git 交付。

项目负责人主要处理目标、重大取舍和结果确认。调查、设计、实施和证据说明由 Agent 完成。Strixnova 保存已经确认的内容和真实执行结果，并检查后续步骤使用的版本、依赖和状态。已有项目可以用它梳理现状并推进改动，新项目也可以用它逐步建立产品、领域、架构和工程材料。

## 你实际会经历什么

普通建设的常规确认分为方向、完整工程方案和实际结果三类。如果这次建设同时建立或实质修订产品定义、领域模型、目标架构或工程政策，Agent 还会单独请你确认这些长期内容；取消、外部执行授权或冲突后的重新确认按实际情况出现。每次请求决定前，Agent 都应主动讲清楚“现在怎样、确认后怎样、为什么这样做、会影响什么、还有哪些风险和未知、本次确认到底授权什么”，并按事情复杂度控制篇幅。你不需要读内部字段或卡片编号；可以用自己的话明确接受或指出需要修改的内容，不必记住固定口令。Agent 解释答复并完整记录原话，程序核对候选、版本和状态；附带修改条件不等于接受原候选。

### 1. 确认方向

你可以从一句日常描述开始。Agent 先查清项目中已有的信息，再和你讨论目标、范围、限制、取舍以及怎样算成功。文件位置、技术结构和工程术语由 Agent 调查和整理。

内容完整后，Agent 会把改前与改后的方向、产品效果、主要取舍和建议集中解释给你。只有那些无法从项目中可靠判断、而且会改变产品方向的问题需要你作决定。方向确认只授权继续调查和形成工程方案，不授权改代码或交付。

### 2. 确认工程方案

Agent 根据已确认的方向和调查事实，说明这次改动会影响什么、准备怎样实施、有哪些风险、怎样验证，以及出现问题时怎样恢复。领域或架构需要调整时，也会放在同一份工程方案里说明。

Strixnova 检查方案的结构、引用、依赖和状态。Agent 还要主动解释实施逻辑、可观察效果、最高影响风险、验证办法和仍未知的内容。你确认后，这份方案成为本地实施与验证依据；这不代表你已经接受实施结果，也不授权 Git 交付、推送或发布。

### 3. 确认实际结果

Agent 按方案修改代码并运行验证。结果展示会逐项列出已经做到的内容、验证状态、偏差和限制。失败、受阻和未运行的项目也会保留原状。

你可以接受结果，也可以退回继续修改。确认之前，代码仍是候选改动；确认之后，Agent 才能按项目规则选择本事项文件形成原子提交，并完成本地合入和安全清理。远程推送、正式发布和部署不在这次确认的授权内。

如果你说“没看懂”或继续提问，Agent 应换一种方式解释同一份候选，不会因此确认、退回或生成新版本。只有你提出会改变候选内容的纠正，才进入修订。Strixnova 只校验候选身份、版本和流程状态，不判断说明是否自然、你是否理解或方案是否正确。

## 各自承担什么

| 参与者 | 职责 |
|---|---|
| 项目负责人 | 说明预期效果，决定产品与领域含义、重大取舍，并接受实际结果 |
| Coding Agent | 调查项目，提出有依据的方向建议和工程方案，实施、验证并解释证据 |
| Strixnova | 校验结构、引用、版本、状态和确定性规则，管理真实命令回执与本地 Git 生命周期 |
| Git 和外部工程工具 | 保存代码与历史，执行测试、构建、发布或部署并返回事实 |

Coding Agent 的启动、调用、认证、调度、会话和团队管理由它所在的宿主负责。Strixnova 关注的是软件建设过程中已经形成的事实、决定、顺序和证据。产品和领域决定来自项目负责人，设计与实现判断来自 Agent，代码历史由 Git 保存。

## DDD 怎样连接到当前代码

现行 DDD 技术包括统一语言、限界上下文、上下文映射和领域不变量追溯。Agent 结合项目资料、代码和用户讨论形成领域候选，目录名与源码类名只是调查线索。项目负责人确认领域含义后，目标架构把领域事实分配给模块、接口和约束，实现对齐再记录当前代码对这些目标的实际覆盖、偏离和未知。

## 多语言实现观察与锚定

Agent 理解代码时，可以自由阅读源码、搜索，并按项目需要使用 AST、LSP、编译器或其他分析工具。Strixnova 不规定这些调查手段，也不记录文件读取次数、搜索方式、上下文或子代理使用。只有工程方案需要建立或更新实现对齐时，Strixnova 才对声明范围运行实现观察，把当前代码与已确认的领域模型和目标架构连接起来。

内置观察器覆盖 Python、Rust、Go、TypeScript / JavaScript、C# 和 C / C++。Python 观察导入关系；Rust、Go 和 TypeScript / JavaScript 观察语言声明、模块或项目清单中的关系；C# 和 C / C++ 只提供保守的部分覆盖。复杂配置和其他语言可以通过已确认工程方案中的外部提供者补充，并且每次执行都需要明确授权。工具不可用、执行失败或只覆盖一部分时，缺口会原样保留。

观察结果包含文件路径与散列、可观察关系、覆盖状态、缺口和运行回执，不包含对业务含义的自动判断。Agent 负责决定文件属于哪个目标模块、架构责任实现到什么程度以及怎样处理偏离。Strixnova 检查候选使用的代码和上游版本是否仍然一致，并阻止覆盖不完整的候选声称完整对齐。候选仍需项目负责人确认后才能采用。具体能力和限制见[实现观察提供者能力矩阵](docs/implementation-alignment/实现观察提供者能力矩阵.md)。

## 怎样开始使用

先按[安装与首次使用](docs/使用说明/installation-and-first-use.md)准备环境并取得对应候选的离线包。Windows x64、Python 3.12 和 Git 是使用者或 Agent 预先准备的条件，Strixnova 离线包提供自身程序、锁定依赖、配套 Skill 和安装入口。本轮生成的候选包位于维护者本地 `.artifacts/candidates/`，不随源代码 Git 提交。

受支持的 Coding Agent 需要实际加载当前安装包随附的唯一 Strixnova Skill。环境准备好后，你可以直接用日常语言告诉 Agent 想做什么，并说明希望它使用 Strixnova 管理这次建设。后续命令和结构化输入由 Agent 依据 Skill 处理。

下面的 `strixnova` 代表安装返回的实际命令入口，Agent 应先核对路径及版本，避免调用同名旧安装。安装后可查看公开入口：

```powershell
strixnova --help
```

普通建设事项使用七个稳定入口：`intake`（受理）、`next`（下一步）、`submit`（提交候选）、`confirm`（确认）、`delivery`（本地交付）、`verify`（验证）和 `cancel`（取消）。CurrentAction（当前动作）及其 InputContract（输入合同）会给出下一步所需的准确内容，Agent 按公开入口和随包 Skill 继续工作，无须从源码、测试夹具、专用插件或钩子推测字段。

日常结构化提交可以使用 `action prepare/preview/apply`，由程序传递精确绑定并组装正式输入。选定材料读取、结果清单、已有测试报告预检等用法见[输入准备与选定材料](skills-cn/strixnova/references/prepared-input.zh-CN.md)。

其他公开入口按用途使用：

- `status`（项目状态）读取工程、验证与运行状态；`status --follow-ups` 独立查询已接受的延期承诺，无需先采用项目长期权威；
- `authority`（长期权威）处理候选展示、复核和负责人决定；
- `alignment`（实现对齐）按已确认的实施安排准备观察、读取结果并写入实现对齐草稿；
- `activity`（外部活动）记录发布、部署等外部计划与真实回执；
- `history`（历史查询）独立读取进行中、已完成和已取消事项的原记录及证据；
- `upgrade`（自身升级）显式维护 Strixnova 程序、配套 Skill 与数据组合。

`strixnova setup-agent` 的作用限于把随包 Skill 复制到 Agent 的技能目录，宿主配置、钩子、插件、凭证和会话管理保持原样。能够直接加载安装包中精确 Skill 的宿主可以省略复制。Skill 提供使用说明；用户授权、身份认证、语义决定和运行状态仍由各自原有的主体负责。

普通用户可以阅读[用户使用指南](docs/使用说明/用户使用指南.md)、[逐项核验与延期跟进](docs/使用说明/逐项核验与延期跟进.md)和[行为例子与测试结果](docs/使用说明/行为例子与测试结果.md)。命令和结构化输入由 Agent 依据随包 Skill 处理。

## 当前产品边界

Strixnova 当前覆盖本地软件工程管理和本地 Git 交付。远程仓库、代码评审和 CI 平台仍由用户及相应外部系统管理，没有独立的 Strixnova 集成。发布、部署、回滚、观测和维护也由外部系统执行，Strixnova 可以管理这些活动的计划、授权、状态、回执和限制。

程序校验能够证明结构、引用、状态、依赖和确定性证据符合合同。产品判断由负责人作出，领域和实现语义由 Agent 审查，真人专家审查与外部认证以实际发生的记录为准。

安装成功、Skill 文件复制、宿主实际加载、Agent 工程行为和正式发布分别说明。当前候选的未验证范围和限制以验证状态为准。

## 文档入口

面向使用者：

- [安装与首次使用](docs/使用说明/installation-and-first-use.md)
- [用户使用指南](docs/使用说明/用户使用指南.md)
- [Coding Agent（智能编码代理）命令手册](docs/使用说明/Coding%20Agent%20命令手册.md)
- [逐项核验与延期跟进](docs/使用说明/逐项核验与延期跟进.md)
- [行为例子与测试结果](docs/使用说明/行为例子与测试结果.md)

产品规则与工程合同：

本仓库当前整合材料仍包含待确认草稿，状态以各材料中的修订和确认记录为准；提交到 Git 不等于完成项目权威采用。

- [项目领域模型、目标架构与工程追溯合同](docs/正式规则/项目领域模型与工程追溯合同.md)
- [工程评估与项目证据合同](docs/正式规则/工程评估与项目证据合同.md)
- [完成归属与轻量收尾合同](docs/正式规则/完成归属与轻量收尾合同.md)

当前工程材料与验证：

- [文档索引](docs/README.md)
- [当前验证状态](docs/engineering/validation-status.md)
- [工程方法来源与边界](docs/engineering/method-sources.md)
- [测试结构与执行](tests/README.md)
- [隔离 Agent 验收方案](docs/engineering/agent-acceptance.md)

当前能力由源码、公开合同和本候选的真实记录共同说明；版本号或说明文字不能代替验证。

## 开发与验证

本仓库当前不使用 CI，测试、构建与隔离安装验收在本地执行。本地测试和构建工具使用
[开发依赖锁文件](requirements-dev-win-py312.txt)，其直接依赖声明见
[requirements-dev-win-py312.in](requirements-dev-win-py312.in)。

开发约束和验证触发规则以 [AGENTS.md](AGENTS.md) 为准。Python 命令使用仓库根虚拟环境；需要源码测试时，先通过受管入口选择受影响范围，例如：

```powershell
.venv\Scripts\python.exe scripts\local_validation.py test -- tests\unit\test_verification_targets.py
```

该入口管理临时目录和证据，成功后回收临时工作区。`tests/repository_checks` 是单独的仓库状态检查，按实际范围显式选择，不混入默认功能回归。具体用法见[本地验证与临时产物管理](docs/使用说明/本地验证与临时产物管理.md)。

普通文档修改默认只做内容复核；实际涉及格式、引用或同步关系时，再做对应检查。不得因为修改 README 或进行本地提交，自动触发全量测试、wheel 构建、隔离安装或 Agent 演练。

只有交付范围明确包含完整候选验收，且内容已冻结时，才运行快速和全量套件：

```powershell
.venv\Scripts\python.exe scripts\local_validation.py test --pin
.venv\Scripts\python.exe scripts\local_validation.py test --full --pin
```

该范围还包括一次 clean wheel、隔离安装、相应仓库状态检查和所需的 Agent 场景。仍匹配的证据可沿用，未运行、失效或受阻的必要项应如实说明，不能宣称完整候选已验收；修复后只重跑受影响层及必要收口。用户对本轮不测试或不验收的明确要求优先。

Strixnova 本身采用普通本地 Git 流程开发，不用 Strixnova 管理自身。远程 Git 操作须由项目负责人明确授权。

第三方方法许可正文只保存在根 README 下方声明区，集中维护来源、采用说明、版权和完整许可正文。随包 Skill 和中文审阅目录不保留许可副本，也不建立副本同步清单。
[声明处理脚本](scripts/third_party_notice.py)供构建入口直接读取本区块，并将内容随 wheel 元数据的长描述携带；不生成独立 NOTICE 或许可文件，声明缺失、被替换或重复时拒绝该构建结果。

研究、设计和历史记录只保留来源及当时的采用依据，不作为当前许可正文的维护入口。工程规范的权利与引用限制仍随[治理来源记录](strixnova/src/strixnova/resources/governance-profile-v1.json)保留，属于出处元数据，不另行维护一份完整许可正文。

<!-- STRIXNOVA-THIRD-PARTY-METHOD-NOTICE:START -->
## 第三方工程方法声明

Strixnova 的部分产品发现、PRD、SPEC 与 UX 形成和复核方法说明参考或改编自 [BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD)。这部分内容依据其 MIT License 使用。Strixnova 是独立项目，与 BMad Code, LLC 不存在从属、认可、认证或兼容承诺。

领域建模、实施、测试、代码复核与原型指引参考了 [Matt Pocock 的 Skills](https://github.com/mattpocock/skills) 中的术语澄清、场景检验、简洁决策记录、模块设计、行为测试、双视角复核和用短期原型回答设计问题的方法，由 Strixnova 在现有权威与执行边界内独立编写。其中领域建模参考 [domain-modeling](https://github.com/mattpocock/skills/tree/main/skills/engineering/domain-modeling) 的方法及术语、ADR 模板，保留 Strixnova 自身的正式来源、事实身份和确认规则。上游采用 MIT License，相关版权和许可列于下方；不引入上游运行依赖、自动同步、品牌认可或兼容承诺。

负责人交互指引参考并改编自 [i-have-adhd](https://github.com/ayghri/i-have-adhd) 的结论前置、状态说明、关注范围控制和具体行动原则，由 Strixnova 在现有事实、执行与确认边界内维护。相关 MIT 版权与许可列于下方；不引入其插件、hooks、会话开关或上游运行依赖。

MIT License

Copyright (c) 2025 BMad Code, LLC

This project incorporates contributions from the open source community.
See [CONTRIBUTORS.md](https://github.com/bmad-code-org/BMAD-METHOD/blob/main/CONTRIBUTORS.md) for contributor attribution.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

TRADEMARK NOTICE:

BMad™, BMad Method™, and BMad Core™ are trademarks of BMad Code, LLC, covering all
casings and variations (including BMAD, bmad, BMadMethod, BMAD-METHOD, etc.). The use of
these trademarks in this software does not grant any rights to use the trademarks
for any other purpose. See [TRADEMARK.md](https://github.com/bmad-code-org/BMAD-METHOD/blob/main/TRADEMARK.md) for detailed guidelines.

Matt Pocock Skills — MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

i-have-adhd — MIT License

Copyright (c) 2026 Ayoub Ghriss

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
<!-- STRIXNOVA-THIRD-PARTY-METHOD-NOTICE:END -->
