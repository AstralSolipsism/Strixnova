# 工程方法来源与使用边界

Strixnova 的责任划分是：项目负责人作出决定、智能编码代理形成工程语义并实施、程序治理确定性状态。

本文件记录当前保留的方法来源和采用边界，不记录先前项目的建设过程、验收结果或兼容承诺。项目内化后的方法由随包 Skill、领域定义、目标架构和工程政策共同维护。

| 来源 | 当前采用内容 | 边界 |
| --- | --- | --- |
| [BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD) | 问题界定、选项比较、假设核对、Product Brief、PRFAQ、PRD、SPEC 与 UX 的形成和复核方法 | 按需形成项目材料；不引入外部运行时、角色体系或命令 |
| [OpenSpec 方法参考](https://github.com/Fission-AI/OpenSpec/tree/6926ccb18afa4ff621112813e9968334576ee11a) | 变更差异与上下游同步思路 | 独立落实到权威变更集；不按标题自动修改正式权威，不成为运行依赖 |
| [Spec Kit 方法参考](https://github.com/github/spec-kit/tree/241d9163640603beb8e2ef1d1223756c7ccdfdb3) | 任务依赖、澄清、分析与清单思路 | 独立落实到实施切片与 Agent 复核，不引入外部模板或扩展体系 |
| [Matt Pocock Skills](https://github.com/mattpocock/skills) | 领域术语、场景检验、模块设计、行为测试、复核与短期原型 | 使用现有权威和确认边界，不增加语义裁决引擎 |
| [i-have-adhd](https://github.com/ayghri/i-have-adhd) | 结论前置、状态说明、关注范围控制与具体行动 | 由项目自己的事实、授权与执行边界约束，不引入插件或 hooks |

第三方版权和许可正文由[根 README](../../README.md)集中维护，并随分发物携带。上表的具体提交链接是来源定位，不是需要兼容、升级或保留的本项目历史。

工程规范来源与独立解释保存在[基础治理档案](../../strixnova/src/strixnova/resources/governance-profile-v1.json)。引用规范、结构验证、程序测试、Agent 复核和负责人接受分别记录，不把任何一项冒充其他证明，也不据此声明获得外部认证。
