"""预约申请领域模型。

定义申请实体、生命周期状态、状态转换规则和撤回业务逻辑。
身份信任来自可信宿主会话，不信任传入角色或所有者字段。
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Optional


class ApplicationStatus(enum.Enum):
    """预约申请生命周期状态。"""

    PENDING = "待审核"
    APPROVED = "已批准"
    REJECTED = "已拒绝"
    WITHDRAWN = "已撤回"


class WithdrawalResult(enum.Enum):
    """撤回操作结果。"""

    SUCCESS = "success"
    ALREADY_WITHDRAWN = "already_withdrawn"
    NOT_OWNER = "not_owner"
    INVALID_STATUS = "invalid_status"
    CONFLICT = "conflict"


@dataclass
class Application:
    """预约申请实体。

    每份申请有独立身份和版本号，用于乐观并发控制。
    """

    application_id: str
    owner_member_id: str
    status: ApplicationStatus = ApplicationStatus.PENDING
    version: int = 1

    @staticmethod
    def create(owner_member_id: str) -> "Application":
        """创建一份新的待审核申请。"""
        return Application(
            application_id=str(uuid.uuid4()),
            owner_member_id=owner_member_id,
            status=ApplicationStatus.PENDING,
            version=1,
        )

    def can_withdraw(self) -> bool:
        """检查当前状态是否允许撤回。"""
        return self.status == ApplicationStatus.PENDING

    def is_already_withdrawn(self) -> bool:
        """检查是否已处于已撤回状态。"""
        return self.status == ApplicationStatus.WITHDRAWN

    def withdraw(self, expected_version: int) -> bool:
        """执行撤回状态转换，使用乐观并发控制。

        Args:
            expected_version: 操作者期望的版本号，必须与当前版本匹配。

        Returns:
            True 表示成功转换，False 表示版本冲突（并发安全）。
        """
        if self.version != expected_version:
            return False
        self.status = ApplicationStatus.WITHDRAWN
        self.version += 1
        return True

    def approve(self, expected_version: int) -> bool:
        """执行审批状态转换，使用乐观并发控制。

        Args:
            expected_version: 操作者期望的版本号。

        Returns:
            True 表示成功转换，False 表示版本冲突。
        """
        if self.version != expected_version:
            return False
        self.status = ApplicationStatus.APPROVED
        self.version += 1
        return True
