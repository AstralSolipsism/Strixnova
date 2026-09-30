# Strixnova 离线安装与首次接入

本说明对应 Windows x64、Python 3.12 的 Strixnova 开发候选。离线包包含 Strixnova wheel、它依赖的 Python 库、安装入口及本说明；不包含 Windows、Python 或 Git 的安装程序，也不包含模型账号。

## 安装前准备

使用者或其 Agent 先准备可运行的 Python 3.12、Git，以及实际业务项目目录。业务项目可以使用其他语言；本说明不扩展实现观察的语言范围。Strixnova 的运行环境与业务项目的开发环境分别管理，不要求复制维护者机器上的目录或环境。

让 Agent 核实要使用的 Python 3.12 可执行文件路径、目标项目目录和 Strixnova 安装目录。每个受管安装目录只属于一个项目，并且与业务项目目录互不包含。新安装目录应不存在或为空；不要使用系统 Python 目录或其他软件的安装目录。

从维护者取得同一候选的完整离线包，解压到普通目录，保留 manifest.json、wheel 和 dependencies 的相对位置。清单用于检查内容完整性，不替代对发布来源的信任。

## 首次安装

在解压目录运行以下入口。路径只是示例，由 Agent 按实际环境填写：

```powershell
.\install.ps1 -PythonPath 'C:\Python312\python.exe' -ProjectDir 'D:\Projects\Shop' -InstallationRoot 'D:\StrixnovaRuntimes\Shop'
```

入口用现有 Python 检查版本、Git 和离线包，在指定安装根的最终位置创建独立 venv，安装锁定依赖和 Strixnova，并核对实际程序、原生入口和随包 Skill。整个安装过程不访问包索引，不安装操作系统，不向系统 Python 安装依赖，不修改 PATH 或 Agent 配置。

安装输出供 Agent 读取，其中 runtime.entrypoint 是实际命令，runtime.python_path 是该隔离解释器，runtime.skill_path 是配套 Skill 目录。无需事先有可用的 strixnova 命令。已选择的相同程序与 Skill 内容可重复检查和使用；已有其他运行组合，或尚无运行选择而项目已有 Strixnova 数据时，首装入口要求改走显式升级，不转换或覆盖旧数据。

若 PowerShell 的现有策略不允许运行脚本，可由 Agent 使用同一个明确的 Python 路径直接调用 Python 入口，不更改系统执行策略：

```powershell
& 'C:\Python312\python.exe' -I -S .\install.py --project-dir 'D:\Projects\Shop' --installation-root 'D:\StrixnovaRuntimes\Shop'
```

## 加载同版 Skill

能够直接读取指定 Skill 的宿主，加载 runtime.skill_path 下的 SKILL.md 即可。需要安装到技能目录的宿主，可以在首装命令中增加 `-SkillsDir '实际技能目录'`，由同版运行程序调用现有 setup-agent 入口复制。已有不同内容时不会静默覆盖；确需替换才显式增加 `-ReplaceSkill`，原内容会备份。

技能目录由宿主实际规则决定，不要因为目录名相似就假定已经加载。确保当前项目使用当前版本，恢复备份不应作为另一份活动 Skill。磁盘文件匹配只证明内容一致；宿主需要重新加载或开启新会话。安装结果的 host_loaded_verified 为 false，不能把文件复制成功当作 Agent 已经读取。

## 在业务项目中开始

让 Agent 使用返回的真实命令查看 `--help`、`upgrade runtime` 和当前项目 `status`，确认调用的是刚才安装的候选。安装不会创建 WorkItem，也不会建立业务产品、领域或架构材料；“安装成功”不等于“项目已正式采用”。

安装可能在项目 `.strixnova/artifacts/maintenance/` 留下正常的协调锁文件。第一个事项通过原有 intake 入口创建，程序会保留这些材料并检查安装是否已收口；无需清空目录。安装仍在进行时等待结束，存在中断记录时按恢复入口处理；损坏记录、不明文件和旧数据库继续受原有保护。

用户可以直接说：“用 Strixnova 管理这个项目。我希望增加……，但不要改变……。”Agent 先调查已有资料和代码，只询问影响目标、业务含义、重要取舍或验收的未决问题。

首次正式实施前，业务目录必须是可用的 Git 根，具有本地集成分支和不可变调查提交，未归属改动需要先处理。Agent 随后按公开合同建立本项目自己的产品定义、领域模型、目标架构、工程政策、实现对齐和工程基线；不要复制 Strixnova 仓库自身的模型作为业务模型。

日常事项分别确认方向、完整方案和实际结果。用户可以自然表达接受、纠正或追问；程序记录精确候选和 Agent 判断，语义由 Agent 解释。首次建立或实质修订长期材料时，明确独立接受范围，并集中展示需要决定的内容。

实际结果接受后才完成本地提交、合入与清理。推送、发布、部署和模型账号仍由相应主体和外部工具负责。

## 数据、升级和排错

事项、确认和运行证据保存在业务项目的 `.strixnova/`，长期工程材料由业务项目 Git 管理。不要把 `.strixnova/`、维护备份或仍被引用的输出当作普通缓存删除；克隆代码不会自动复制这些本地记录。

维护已有 Strixnova 安装时，使用同版 Skill 的 history-and-upgrade 指引，通过 upgrade check/apply 明确绑定程序、Skill 与同格式数据组合。初始 Authority、活动库和证据格式各为 v1，以 `strixnova upgrade runtime` 返回的当前支持范围为准。未收口执行会阻止维护；恢复核对原始备份、切换身份和后续业务事实，不用旧备份覆盖新记录。

缺少 Python、Git、依赖 wheel，包校验不匹配，安装目录被占用或 Skill 目录冲突时，入口会给出错误。先按错误处理真实条件，不拼造成功回执；已准备的安装会保留，以便重试或恢复。这里的技术检查不证明 Agent 使用效果或真实用户满意度。
