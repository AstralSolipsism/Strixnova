# 同一批关系的有限补读

先前作者候选未获独立通过：12 项中 1 项通过、11 项需要修订。原评价及独立报告会保留。本次不改变任何合同，不预设 implemented，不能仅删除 limitations 中的未读说明来制造通过。

请根据当前 packet 的目标合同和真实源码，补读以下被独立审阅指出的关键实现；材料均已复制到 inputs/files，使用其真实 read_path。先定位具体方法再读完整相关分支，不用模块开头的 import 代替调用、数据流或副作用边界。

1. RELATION-6EAD97D4D62148C3：project_authority_consistency 的 _load_authority_batch 及读取器复用、批次缓存生命周期；核对一次查询与跨命令边界。
2. RELATION-70C02DA513464315：project_product_definition 的实际读取方法、路径/版本与来源元数据范围。
3. RELATION-724D5792704F4A15、RELATION-7395E3C1708D4FC2、RELATION-7E4EB885A1494685：禁止关系不能仅凭没有顶层 import 判定；核对相关模块完整调用入口和实现路径，区分直接加载、协作读取与禁止的业务决定。packet 可用于查找合同，实际行为结论须引用实现或断言。
4. RELATION-74419EB86BFF4394：implementation_observation 对声明观察范围、规范字节、路径清单和不可变版本身份的实际读取链路。
5. RELATION-78931C91B5ED4A67：project_implementation_alignment 消费领域目录、类型与闭包的具体方法；实现判断的保存边界。
6. RELATION-7A3BA2436725405C：through_module 模式要求实际核对协调器的授权前置条件及中介两段调用路径，不以两边存在 import 代替。
7. RELATION-7DFF1E0E5CD74294：review_context_projection._read 及对齐读取的真实映射，区分项目与仓库事实。
8. RELATION-7F4A91B2C3D4E5F6：git_workspace 复用严格路径身份解码与不可变提交路径比较的实际方法及调用边界。
9. RELATION-8431BBE65FA54B8E：governance_context() 的实现与下游消费方式，核对经校验摘要的边界。

每项分别给出实际读取的关键源码位置与相应断言/观察记录。没有充分依据时保留 unknown 或 partially_implemented，并准确列出未核实点，不把证据局限包装成完整支持。原先通过的一项也按当前输入独立核对；整体产品、Agent 效果与负责人接受不在本次实现关系评价范围内。

按原有结构化 Schema 输出全部 12 项。仅引用真实存在的文件行号或 packet 提供的 actual-dependencies.yaml#/records/N 位置，不能猜行号或用宽泛头部范围掩盖未读。
