"""Create a current-format maintenance fixture with one genuinely interrupted write."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'strixnova/src'),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from strixnova.process_supervisor import ProcessPolicy,ProcessLimits,run_process

work=ROOT/'.artifacts/validation/d5ba73f19ec8/work';evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
source=candidate(ROOT/'.artifacts/candidates/initial-guidance/candidate.json')
target=candidate(ROOT/'.artifacts/candidates/initial-v1/candidate.json')
assert source['build_sha256']!=target['build_sha256']
project=work/'project';assert project.is_dir() and (project/'.git').is_dir()
inputs=project/'.agent-inputs';assert inputs.is_dir()
def cli(*args):
    result=subprocess.run([source['entrypoint'],*args,'--project-dir',str(project)],capture_output=True,text=True,encoding='utf-8',timeout=45)
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    return json.loads(result.stdout)
created=json.loads((work.parent/'evidence/intake.json').read_text(encoding='utf-8'));dump(evidence/'intake.json',created)
identifier=created['next']['work_item_id']
before=cli('history','--work-item-id',identifier,'--record','request','--record','events')
dump(evidence/'initial-history.json',before)
script=work/'owned_interrupted_writer.py'
assert not script.exists(), 'Do not repeat the registered business effect'
script.write_text('''from pathlib import Path
import json,os,sys
from strixnova.project_maintenance import project_operation
project=Path(sys.argv[1])
print(json.dumps({"pid":os.getpid(),"script":"owned_interrupted_writer.py","explicit_child_launches":0}),flush=True)
with project_operation(project,operation_name="fixed-maintenance-output"):
    output=project/".strixnova/artifacts/fixed-business-output.txt"
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("ab") as stream:
        stream.write(b"business-effect: recorded-once\\n")
        stream.flush()
        os.fsync(stream.fileno())
    os._exit(23)
''',encoding='utf-8',newline='\n')
argv=[source['installed_python'],'-I','-B','-X','utf8',str(script),str(project)]
result=run_process(argv,cwd=project,policy=ProcessPolicy.exact('strixnova-g9-owned-process-v1','单个已登记隔离进程产生真实副作用后退出，不执行结束记录。',argv),limits=ProcessLimits(timeout_seconds=20))
assert result.exit_code==23
owned=json.loads(result.stdout.decode('utf-8'))
dump(evidence/'owned-process-exit.json',{'argv':argv,'pid':owned['pid'],'exit_code':result.exit_code,
 'stdout':result.stdout.decode('utf-8'),'stderr':result.stderr.decode('utf-8'),
 'duration_seconds':result.duration_seconds,'process_supervisor_returned_without_cleanup_error':True,
 'script_sha256':sha(script),'script_declares_no_descendant_launches':True,
 'scope':'Only the exact process launched through the existing process supervisor; no host-wide process claim.',
 'source_candidate':source})
shutil.copyfile(script,evidence/'owned_interrupted_writer.py')
ops=cli('upgrade','operations');dump(evidence/'interrupted-operations.json',ops)
assert len(ops['operations'])==1 and ops['operations'][0]['state']=='interrupted'
operation=ops['operations'][0];record=project/'.strixnova/artifacts/maintenance'/(operation['operation_id']+'.json')
shutil.copyfile(record,evidence/'original-start-record.json')
output=project/'.strixnova/artifacts/fixed-business-output.txt'
assert output.read_bytes()==b'business-effect: recorded-once\n'
observations=work/'observations';observations.mkdir()
dump(observations/'setup-provenance.json',{'source_files':{output.relative_to(project).as_posix():sha(output)}})
installation=work/'dedicated-installation'
fixed_inputs={
 'check':'请读取本工程AGENTS.md、指定Skill与maintenance-inputs.json。先只读检查这个明确的临时项目能否更新至给定本地候选，说明当前身份、保护内容和阻断。本条只授权检查；不要恢复、安装、删除标记或重复业务命令。到发现真实阻断后停止，等待后续材料。',
 'recover_and_update':'现在已提供本次登记操作的真实执行与停止材料，见.actor-evidence目录。请核对精确操作scope、原始脚本、退出和副作用记录，按公开停止证据合同收口该操作，再按maintenance-inputs.json中已指定的源/目标与专用目录继续本临时项目的维护更新。只处理本操作，不重跑业务脚本、不删标记、不改写格式版本，不把进程退出直接等同于业务完成；按现有接口保留原记录、备份并验证实际目标入口。不要操作其他项目或普通宿主安装。',
 'reload':'本条在已验证的新运行组合上检查加载。请重新读取本项目AGENTS.md及当前已复制的配套Skill，使用其指定的新入口查询原事项历史并说明实际程序/Skill身份、原始输出保全和维护状态。只读，不重复更新或业务命令；明确这只证明当前新会话的显式加载，不外推普通宿主自动加载。',
}
settings={'source_entrypoint':source['entrypoint'],'source_python':source['installed_python'],
 'target_wheel':target['wheel'],'target_wheel_sha256':target['wheel_sha256'],
 'target_build_sha256':target['build_sha256'],'target_skill_sha256':target['skill_sha256'],
 'installation_root':str(installation),'builder_python':sys.executable,
 'wheelhouse':str(ROOT/'.artifacts/wheelhouse/win-py312'),'work_item_id':identifier,
 'formats':'Current Authority/Activity/evidence format1 only; no format conversion.'}
dump(project/'maintenance-inputs.json',settings)
(project/'AGENTS.md').write_text(f'''# 固定维护验收

这是专用临时工程。使用 .agents/skills/strixnova/SKILL.md 及实际存在的 history-and-upgrade.md。源公开CLI见maintenance-inputs.json。目标wheel、专用安装根与锁定wheelhouse是明确授权的测试资源，允许通过公开维护入口访问；不读取 Strixnova 私有实现，不访问其他业务工程或修改普通宿主安装，不调用子Agent。

所有Python命令（包括临时JSON处理）必须使用 `{sys.executable}`，禁止裸python、python3或py。源与目标安装解释器只由公开维护/安装接口作已安装制品检查。临时请求写入 .agent-inputs/，原始业务输出不得改写。本阶段具体授权以当次消息为准；测试输入不是实际负责人对真实Strixnova项目的接受。
''',encoding='utf-8',newline='\n')
info={'group':'G9','project':str(project),'source_candidate':source,'target_candidate':target,
 'installation_root':str(installation),'work_item_id':identifier,'operation':operation,'operation_record':str(record),
 'original_record_sha256':sha(record),'business_output':str(output),'business_output_sha256':sha(output),
 'settings':settings,'fixed_inputs':fixed_inputs,'author_model':'gemini-3.8-flash-low',
 'reviewer_model':'gemini-3.8-flash-low','permission_mode':'auto_approve','os_isolation_verified':False,
 'owner_accepted':False,'scope':'One real current-format interrupted write, explicit same-format installation update and new-session load.'}
dump(work/'fixture.json',info);dump(evidence/'fixture.json',info);shutil.copyfile(__file__,evidence/'operator-source.py')
print(json.dumps({'fixture':str(work/'fixture.json'),'operation_id':operation['operation_id'],'actual_exit_code':result.exit_code,
 'source_build':source['build_sha256'],'target_build':target['build_sha256'],'native_acceptance_started':False},ensure_ascii=False))
