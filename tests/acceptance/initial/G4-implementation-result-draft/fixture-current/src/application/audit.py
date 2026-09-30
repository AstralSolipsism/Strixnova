"""审计日志记录模块。

保留操作者、原状态、新状态和操作身份。
重复撤回（幂等）不新增审计记录。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .domain import ApplicationStatus


@dataclass
class AuditEntry:
    """一条审计记录。

    Attributes:
        operator_member_id: 执行操作的成员身份。
        application_id: 被操作的申请身份。
        previous_status: 操作前的状态。
        new_status: 操作后的状态。
        action: 操作类型（如"撤回"）。
    """

    operator_member_id: str
    application_id: str
    previous_status: ApplicationStatus
    new_status: ApplicationStatus
    action: str


class AuditLog:
    """审计日志存储。

    简单的内存存储，保存所有审计记录。
    """

    def __init__(self) -> None:
        self._entries: List[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        """记录一条审计条目。"""
        self._entries.append(entry)

    def entries_for(self, application_id: str) -> List[AuditEntry]:
        """返回指定申请的全部审计记录。"""
        return [e for e in self._entries if e.application_id == application_id]

    @property
    def all_entries(self) -> List[AuditEntry]:
        """返回全部审计记录（只读副本）。"""
        return list(self._entries)
