# 本轮评价的引用与范围

所有文件只读，只通过最终结构化输出返回，不写 assessment.json 或解析脚本。

每条 evidence.ref 必须为实际读取的冻结文件及有效行号：优先 `inputs/files/原仓库相对路径#L起行-L止行`，包中测试执行定位可用 `inputs/packet.json#L起行-L止行`。不要用「本轮说明」「全文覆盖」等泛称，不合并多个文件名，不虚构或颠倒行号。文件总行数见 packet.files 的 line_count。claim 限定该位置实际支持的结论，多文件证据分条填写。

对于关系的实际依赖底账，packet.targets[].dependency_record_locators 列出了程序按真实记录位置生成的 `docs/implementation-alignment/actual-dependencies.yaml#/records/索引` 定位。请读取对应记录后使用该精确引用，多个记录分别列证据；不要猜成首100行。此定位只证明记录身份，记录分类仍不能代替实际调用或中介边界的语义核查。

逐项读取关系或约束正文及相关当前代码/断言，不把名称匹配、import 存在、测试数量、另一模块已有评价当充分证明。direct/read_only_projection 检查实际调用方向与写能力；through_module 检查中介两段调用；forbidden 检查可见绕过路径并说明动态调用证据边界。约束包含程序机制、行为验证或人工复核时应分别说明证据，不把静态文字自动升级为真实 Agent 场景通过。

实现评价与证据充分程度要分别表述；未知保持未知，真实未实现职责列入 missing 和 resolution_plan。Git 绑定、Agent 语义、负责人接受仍有明确边界，不因此忽略已直接观察的代码职责，也不以代码评价代替这些接受。source_ownership 对关系和约束为空数组。

避免重复抄写整段代码或对同一来源反复全文输出；用精确引用与必要说明保持可审阅。不预设任何目标通过。
