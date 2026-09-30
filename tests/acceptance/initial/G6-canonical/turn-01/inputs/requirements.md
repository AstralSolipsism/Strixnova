# 预约时长小组件

这是隔离验收的合成需求。调用方提供整数分钟刻度。duration(start, end) 在 end 严格大于 start 时返回正的 end-start；不合法顺序抛出 ValueError。此变更新增 reservation_limits.py，以 MAX_RESERVATION_MINUTES=120 暴露配置常量；本次不要求 duration 执行该上限，也不增加类型或日期格式转换。
