# 同一关系评价会话的有限输出修正

上一轮 2a50f7f5eaf5 已达到 900 秒期限并结束，全部读取工具已收口，冻结输入保持不变。原始错误和未完成结果已保存，不能称为通过。

实际 finish 错误显示 `satisfied` 先被作为布尔值、后被作为文本 `true` 提交，均不符合现有底账要求。其他早期错误还包括 null 数组和不存在的 evidence.kind。请继续同一会话，基于已读原始合同、代码和断言，对原 12 条关系提交完整、可复核的结构化评价，不重新建立业务工程，也不预设 implemented。

字段类型必须为：
- satisfied、missing、resolution_plan、limitations、deviation_ids：字符串数组。satisfied 应列出具体受支持的合同职责。空值是 []，不能是 true、"true" 或 null。
- evidence：对象数组，kind 只允许 source/test/artifact/command/inspection；ref 是真实冻结文件和有效行号，claim 是该位置实际支持的内容。
- source_ownership：本组是关系评价，返回 []。
- owner_accepted、semantic_content_machine_proven：false。

保留原范围、标准和所有实际限制；未核实点按现有合同保留具体缺口，不为收口降低判定要求。只补必要读取，不反复全文读取相同文件。所有文件只读，通过最终结构化通道返回，不写文件、运行产品或调用子Agent。
