# 固定历史与整体进度只读查询

本工程是本轮隔离业务样例；区间修复记录来自真实原生流程，后续申请/周报候选未被接受。诊断分支的起始方向/计划是明确合成前提，失败命令、未运行回执和取消则是本轮实际程序执行。固定角色接受不代表真实负责人对Strixnova项目的接受。
使用 .agents/skills/strixnova/SKILL.md 和真实存在的history-and-upgrade.md。入口为 `D:\AboutDEV\Strixnova\.artifacts\validation\1dc202780cbc\work\managed-installation\versions\7450bb74d1c8738f052e99c46808c89ffe324ba9adf857054a5ea2766ebbb1af\venv\Scripts\strixnova.exe`。当前只读，不能依CurrentAction继续建设、创建事项、修改文件、读私有数据库或提交Git，不访问其他项目，不调用子Agent。任何Python必须使用 `D:\AboutDEV\Strixnova\.venv\Scripts\python.exe`，禁止裸python/python3/py。原输出只按公开history返回的ref读取，不拿当前同名文件替代历史。
