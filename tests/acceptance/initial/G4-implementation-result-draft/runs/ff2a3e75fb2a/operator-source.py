"""Ask the same independent reviewer to verify three source-level discrepancies."""
from pathlib import Path
import json,os,shutil,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump,sha
from scripts.review_antigravity_evidence import reconsider_review
previous=ROOT/'.artifacts/validation/f2aae50a843d/evidence'
terminal=json.loads((previous.parent/'result.json').read_text(encoding='utf-8'))
assert terminal['process_settled'] and terminal['status']=='passed'
binding=json.loads((previous/'gate-binding.json').read_text(encoding='utf-8'))
assert binding['phase']=='G4-draft-content-only' and not binding['fixed_input_dispatch_permitted']
initial=json.loads((ROOT/'.artifacts/validation/f0af53c1b14a/evidence/registration.json').read_text(encoding='utf-8'))
project=Path(initial['project'])
assert all(sha(project/name)==digest for name,digest in binding['candidate_files'].items())
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
feedback='''请在同一冻结材料、同一内容验收范围内重新核对以下具体疑点，不预设结论。原passed报告保留。本次仍不得登记结果、改写代码、执行工作流或替代作者，且固定接受输入保持禁止。

1. 可信身份：原报告称MemberService.withdraw与CLI均严格以已认证身份为基准。file/src/cli.py的build_parser允许调用者提供--member-id，run_cli将args.member_id直接传入authenticated_member_id；file/src/application/service.py的withdraw只比较这个参数与owner_member_id，文档把认证交给调用方。请沿实际调用路径查明可信宿主会话在何处提供/校验身份，或是否仅有参数名称和注释的假定。对照draft-actual-result的完整能力声明及当前限制，判断原结论是否有相称依据；若有真实保障路径，请引用该路径，若没有请按原标准报告。

2. CLI实际可用性：file/src/cli.py定义build_parser和run_cli，但源码中没有顶层入口调用；file-inventory列出了实际可交付文件。请核对是否存在可执行的宿主装配/启动路径及实际运行证据，区分函数级接口与草稿所称完整本地终端能力。不能只以argparse出现作为实际贯通依据，也不新增原方案未要求的部署范围。

3. 并发与状态：file/src/application/service.py先调用can_withdraw，之后才取expected_version并调用withdraw；file/src/application/domain.py的withdraw/approve分别检查版本后写状态和递增，withdraw内部未检查待审核状态。file/tests/test_withdrawal.py中的并发用例是读取版本后顺序调用。请核对该证据能支持多大的并发保证，尤其服务层状态检查与版本读取之间发生审批时，以及版本比较和更新的原子性。若当前实现或测试不能支持草稿的声明，确认是否已经如实披露；勿把版本字段存在或顺序模拟直接升级为并发保证。

请返回原JSON结构，对每个实际问题给出冻结source_id及正确行号。若查证没有问题，也应解释上述实际数据流和执行边界，不能仅重复作者注释或草稿自述。'''
(evidence/'review-feedback.txt').write_text(feedback,encoding='utf-8')
shutil.copyfile(__file__,evidence/'operator-source.py')
dump(evidence/'registration.json',{'reviewer_model':initial['reviewer_model'],'previous_review_run':'f2aae50a843d',
    'scope':'Same draft-content criteria and frozen inputs; no workflow execution or acceptance.',
    'feedback_sha256':sha(evidence/'review-feedback.txt'),'timeout_seconds':600,'owner_accepted':False})
review=reconsider_review(previous/'independent-review',evidence/'independent-review',feedback,timeout=600)
assert all(sha(project/name)==digest for name,digest in binding['candidate_files'].items())
passed=review['execution']['report_valid'] and len(review['cases'])==1 and review['cases'][0]['summary']['status']=='passed'
binding.update({'content_review_passed':passed,'fixed_input_dispatch_permitted':False,
    'prior_content_review':str(previous/'independent-review/review.json'),
    'review_report':str(evidence/'independent-review/review.json'),
    'review_report_sha256':sha(evidence/'independent-review/review.json')})
dump(evidence/'gate-binding.json',binding)
print(json.dumps({'report_valid':review['execution']['report_valid'],'content_review_passed':passed,
    'native_verdict':review['cases'][0]['verdict'] if review['cases'] else None,
    'fixed_input_dispatch_permitted':False,'owner_accepted':False},ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] else 1)
