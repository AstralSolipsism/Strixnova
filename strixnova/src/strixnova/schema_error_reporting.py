"""Small helpers for actionable public JSON Schema failures."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_TYPE_NAMES = {
    "array": "数组",
    "boolean": "布尔值",
    "integer": "整数",
    "null": "空值",
    "number": "数字",
    "object": "对象",
    "string": "文本",
}
_FORMAT_NAMES = {
    "date": "YYYY-MM-DD 日期",
    "date-time": "ISO 8601 日期时间",
    "duration": "ISO 8601 时长",
    "email": "电子邮箱",
    "hostname": "主机名",
    "ipv4": "IPv4 地址",
    "ipv6": "IPv6 地址",
    "regex": "正则表达式",
    "time": "时间",
    "uri": "URI 地址",
    "uuid": "UUID 标识",
}


def one_of_branch_errors(error: Any, branch_index: int | None) -> list[Any]:
    """Select the known discriminator branch instead of every oneOf branch."""

    if (
        branch_index is None
        or error.validator != "oneOf"
        or not error.context
    ):
        return [error]
    selected = [
        item
        for item in error.context
        if list(item.schema_path)
        and list(item.schema_path)[0] == branch_index
    ]
    return selected or [error]


def schema_error_message(error: Any) -> str:
    """Turn common JSON Schema failures into concise actionable Chinese."""

    if error.validator == "required" and isinstance(error.instance, Mapping):
        missing = sorted(set(error.validator_value) - set(error.instance))
        if missing:
            return "缺少必填字段：" + ", ".join(missing)
    if error.validator == "additionalProperties" and isinstance(
        error.instance,
        Mapping,
    ):
        allowed = set((error.schema.get("properties") or {}).keys())
        unexpected = sorted(set(error.instance) - allowed)
        if unexpected:
            return "包含不允许字段：" + ", ".join(unexpected)
    if error.validator == "enum":
        return (
            f"值 {error.instance!r} 不在允许集合中："
            + ", ".join(repr(item) for item in error.validator_value)
        )
    if error.validator == "const":
        return f"值必须是 {error.validator_value!r}"
    if error.validator == "type":
        expected = error.validator_value
        if isinstance(expected, list):
            expected_text = "、".join(
                _TYPE_NAMES.get(str(item), str(item)) for item in expected
            )
        else:
            expected_text = _TYPE_NAMES.get(str(expected), str(expected))
        return f"值类型必须是{expected_text}"
    if error.validator == "format":
        selected = str(error.validator_value)
        return f"值必须符合{_FORMAT_NAMES.get(selected, selected)}格式"
    if error.validator == "pattern":
        return f"值不符合格式 {error.validator_value}"
    if error.validator == "minItems":
        return f"至少需要 {error.validator_value} 项"
    if error.validator == "maxItems":
        return f"最多允许 {error.validator_value} 项"
    if error.validator == "minProperties":
        return f"对象至少需要 {error.validator_value} 个字段"
    if error.validator == "maxProperties":
        return f"对象最多允许 {error.validator_value} 个字段"
    if error.validator == "minLength":
        return f"文本长度至少为 {error.validator_value}"
    if error.validator == "maxLength":
        return f"文本长度最多为 {error.validator_value}"
    if error.validator == "minimum":
        return f"数值不得小于 {error.validator_value}"
    if error.validator == "maximum":
        return f"数值不得大于 {error.validator_value}"
    if error.validator == "exclusiveMinimum":
        return f"数值必须大于 {error.validator_value}"
    if error.validator == "exclusiveMaximum":
        return f"数值必须小于 {error.validator_value}"
    if error.validator == "uniqueItems":
        return "列表内容不得重复"
    if error.validator == "oneOf":
        return "值不符合任何一个允许的结构分支"
    if error.validator == "anyOf":
        return "值不符合任一允许条件"
    if error.validator == "not":
        return "值命中了明确禁止的结构"
    return f"值不符合结构规则：{error.validator}"


__all__ = ["one_of_branch_errors", "schema_error_message"]
