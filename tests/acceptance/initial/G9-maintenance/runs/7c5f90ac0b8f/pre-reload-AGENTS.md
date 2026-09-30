# 固定维护验收

这是专用临时工程。使用 .agents/skills/strixnova/SKILL.md 及实际存在的 history-and-upgrade.md。源公开CLI见maintenance-inputs.json。目标wheel、专用安装根与锁定wheelhouse是明确授权的测试资源，允许通过公开维护入口访问；不读取 Strixnova 私有实现，不访问其他业务工程或修改普通宿主安装，不调用子Agent。

所有Python命令（包括临时JSON处理）必须使用 `D:\AboutDEV\Strixnova\.venv\Scripts\python.exe`，禁止裸python、python3或py。源与目标安装解释器只由公开维护/安装接口作已安装制品检查。临时请求写入 .agent-inputs/，原始业务输出不得改写。本阶段具体授权以当次消息为准；测试输入不是实际负责人对真实Strixnova项目的接受。
