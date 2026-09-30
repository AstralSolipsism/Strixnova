# 当前仓库状态检查

这一组检查 Strixnova 仓库当前源码、长期材料和已登记证据是否一致。它保留文件指纹、实际依赖、领域与架构引用、责任覆盖、偏离记录以及日常门和阶段门的检查。

它不属于普通功能回归，默认 `pytest` 的 `testpaths` 只收集 `tests/unit` 与 `tests/integration`。需要检查当前仓库材料时显式运行：

```powershell
.venv\Scripts\python.exe scripts\local_validation.py test -- tests\repository_checks
```

失败表示相应仓库状态检查没有满足，需阅读具体原因；例如源码变化后旧对齐快照尚未复核，不能直接解释为功能逻辑回归失败。也不能通过只改指纹或删除断言宣称新材料已经验收。

真正验证 Strixnova 对齐行为的测试位于 `tests/unit/test_implementation_observation_drift.py` 和 `tests/unit/test_target_alignment_gate.py`。它们使用 `tests/support/implementation_alignment.py` 创建的隔离样例，分别验证未变化时通过、源码或依赖变化时报告失效、缺失证据被拒绝，以及阶段门对确认状态的约束。

历史 Agent 回执的内容匹配仍由 `scripts/check_guided_formation_acceptance.py` 单独报告；`stale` 不表示重新运行场景失败。本次测试分组调整不刷新历史指纹或已确认的实现快照。
