# 行为例子与核验（中文审阅映射）

形成会改变用户或外部调用方可观察行为的方向，或当前计划包含行为例子时读取。沿用方向、方案、验证和实际结果记录保存例子、执行证据与接受。

## 先明确期望，再选择测试

strixnova.direction-decision.v1 的每项验收填写 behavior。可观察行为变化使用 applicability required 和 examples；纯说明或保持行为的机械修改使用 not_applicable 并解释具体原因。undetermined 必须说明原因，且只允许在有阻碍的草稿中，不能进入方向确认。适用性和充分性由 Agent 判断，程序检查结构和引用。

先从用户请求及其真实需求、约束得出预期，再看已有测试。覆盖正常路径以及相关拒绝、边界或恢复情形，不虚构范围。例如：

~~~json
{
  "applicability": "required",
  "examples": [{
    "example_id": "DIREX-0123456789ABCDEF",
    "title": "库存不足时库存保持不变",
    "given": ["可用库存为 2 件"],
    "when": "调用方预留 3 件",
    "then": ["请求被拒绝", "可用库存仍为 2 件"],
    "basis_refs": ["direction.requirement:DIRREQ-0123456789ABCDEF"]
  }]
}
~~~

写入所属验收的 behavior，只能引用该验收自身需求及当前方向约束，不能引用无关需求或任意测试文件。首次创建 WorkItem 内的随机 DIREX- 身份，后接 16 位大写十六进制；澄清保留，含义变化更换，退役后不复活。在原有方向卡中用日常语言说明，用户无需维护 ID 或测试语法。

## 每个例子都安排具体核验

strixnova.engineering-assessment.v1 对每个 direction.example:DIREX-* 安排核验。自动执行使用带 case_report 的命令；其他情况沿用 verification_reviews 的 agent_review、existing_evidence 或 not_verified，说明限制和旧证据适用性。有例子的父验收从子例子推导结果；只覆盖父验收不能绕过子例子遗漏。

真实 pytest 命令在 argv、cwd、run_kind、reason 和 covers 之外填写 case_report：

~~~json
{
  "adapter": "pytest",
  "test_root": ".",
  "input_paths": ["inventory.py", "tests/test_inventory.py", "pytest.ini"],
  "bindings": [{
    "example_ref": "direction.example:DIREX-0123456789ABCDEF",
    "test_ids": ["tests/test_inventory.py::test_insufficient_stock"]
  }]
}
~~~

test_ids 使用相对 test_root 的原生 pytest node ID，参数化测试带精确参数后缀；从真实项目或定点收集确认，不使用展示标签、通配符或猜测名称。test_root 和 input_paths 均相对执行仓库，不是命令 cwd。逐文件列出本行为需要的源码、测试、夹具及配置，必须包含绑定测试文件；不接受目录、通配符、仓库外路径、.git 或 .strixnova，不快照一次性输出或可变测试数据。

这是声明的输入范围，不自动发现全部依赖；Agent 必须检查遗漏依赖和范围外变化。strixnova.engineering-plan.v1 编译时生成 example_fingerprints，不手写这些指纹，也不在评估中复制例子正文。一条计划命令的一份报告可绑定多个例子和原生用例；不要为每个例子分别建立全量运行、目录或报告。

## 区分实际执行与断言审阅

实施时只运行当前需要的最小反馈测试。适用测试先行时，先观察预期行为错误再修复；跳过的脚手架或导入错误不算这类失败。实现准备好后复用原计划最终命令。

`strixnova verify` 仅向该子进程注入随包 pytest 报告器。目标环境必须已有 pytest；Strixnova 不安装测试框架，不修改项目配置。首批适配 pytest 与 pytest-xdist；其他框架完成自身适配前不能声称获得原生用例执行证据。

strixnova.test-case-report.v1 记录原生用例、执行阶段、框架与 Python 版本、运行身份和报告器身份。strixnova.test-case-evidence.v1 将报告绑定到当前方案、例子内容与声明输入的实际字节，包括未提交改动。命令通过不能把 skipped、xfailed、xpassed、deselected、not_collected、not_run、failed 或 error 用例变成已通过例子。报告缺失、无效或输入变化保留明确缺口；执行后声明输入改变必须重新运行，旧回执仍保留为历史。行为本身改变时返回方向修订。

实际结果中，除非命令安排的结果外，每个自动例子也要通过 verification_review_results 提交断言充分性审阅，使用 target_ref、outcome、rationale 和 evidence_refs。outcome 为 supported、not_supported 或 not_verified；根据真实源码和回执引用，审阅断言是否检查了承诺结果和相关副作用。某个原生测试 ID 通过本身不等于完成审阅。计划中的 assertion_review_required 明示该义务。

程序结合审阅与实际回执推导 target_verification，分别呈现 command_result、report_status、tests 和 assertion_review。未获支持或不完整的例子必须保留实际结果限制；semantic_content_machine_proven 始终为 false。原有结果卡按“期望例子、实际观察、充分性审阅、剩余缺口”说明。

每条命令仅一份报告，和 stdout/stderr 一起存放于 .strixnova/artifacts/<WorkItem-ID>/<receipt-ID>.cases.json。通过 strixnova history 读取返回的 output:<receipt-ID>:cases 引用，沿用分页、可用性与散列核验；不得伪造或手改报告。新评估和重规划使用当前方向合同；已记录工作保留真实证据和限制，不追认成已通过例子验证。
