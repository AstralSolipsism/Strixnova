"""成员服务层。

协调身份验证、归属检查、状态检查、撤回执行和审计写入。
身份来自可信宿主会话，不信任传入角色或所有者字段。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .audit import AuditEntry, AuditLog
from .domain import Application, ApplicationStatus, WithdrawalResult


@dataclass
class WithdrawalResponse:
    """撤回操作的响应。

    Attributes:
        result: 撤回操作结果。
        application_id: 被操作的申请身份。
        current_status: 操作后申请的当前状态。
    """

    result: WithdrawalResult
    application_id: str
    current_status: ApplicationStatus


class MemberService:
    """成员服务。

    管理申请存储，处理撤回请求，维护审计日志。
    使用可信宿主会话中的成员身份，不信任传入参数中的角色字段。
    """

    def __init__(self) -> None:
        self._applications: Dict[str, Application] = {}
        self._audit_log = AuditLog()

    @property
    def audit_log(self) -> AuditLog:
        """暴露审计日志供查询。"""
        return self._audit_log

    def register_application(self, app: Application) -> None:
        """注册一份申请到存储中。"""
        self._applications[app.application_id] = app

    def get_application(self, application_id: str) -> Optional[Application]:
        """查询申请。返回 None 表示不存在。"""
        return self._applications.get(application_id)

    def withdraw(
        self,
        authenticated_member_id: str,
        application_id: str,
    ) -> WithdrawalResponse:
        """处理撤回请求。

        流程：成员认证（由调用方保证）→ 校验归属 → 校验状态 → 乐观并发撤回 → 审计记录。

        Args:
            authenticated_member_id: 已认证的成员身份（来自可信宿主会话）。
            application_id: 要撤回的申请身份。

        Returns:
            WithdrawalResponse 包含操作结果和当前状态。
        """
        app = self._applications.get(application_id)
        if app is None:
            return WithdrawalResponse(
                result=WithdrawalResult.NOT_OWNER,
                application_id=application_id,
                current_status=ApplicationStatus.PENDING,
            )

        # 校验归属：一名成员只能操作本人申请
        if app.owner_member_id != authenticated_member_id:
            return WithdrawalResponse(
                result=WithdrawalResult.NOT_OWNER,
                application_id=application_id,
                current_status=app.status,
            )

        # 幂等性：已撤回状态下重复撤回返回相同结果，不新增审计记录
        if app.is_already_withdrawn():
            return WithdrawalResponse(
                result=WithdrawalResult.ALREADY_WITHDRAWN,
                application_id=application_id,
                current_status=ApplicationStatus.WITHDRAWN,
            )

        # 状态限制：只允许待审核状态撤回
        if not app.can_withdraw():
            return WithdrawalResponse(
                result=WithdrawalResult.INVALID_STATUS,
                application_id=application_id,
                current_status=app.status,
            )

        # 乐观并发撤回
        previous_status = app.status
        expected_version = app.version
        if not app.withdraw(expected_version):
            return WithdrawalResponse(
                result=WithdrawalResult.CONFLICT,
                application_id=application_id,
                current_status=app.status,
            )

        # 审计记录：保留操作者、原状态、新状态和操作身份
        self._audit_log.record(
            AuditEntry(
                operator_member_id=authenticated_member_id,
                application_id=application_id,
                previous_status=previous_status,
                new_status=ApplicationStatus.WITHDRAWN,
                action="撤回",
            )
        )

        return WithdrawalResponse(
            result=WithdrawalResult.SUCCESS,
            application_id=application_id,
            current_status=ApplicationStatus.WITHDRAWN,
        )

    def query_status(self, application_id: str) -> Optional[ApplicationStatus]:
        """查询申请的实际当前状态。

        用于响应丢失后确认操作结果。

        Returns:
            当前状态，或 None 表示申请不存在。
        """
        app = self._applications.get(application_id)
        if app is None:
            return None
        return app.status
