"""撤回行为的单元测试和集成测试。

覆盖全部方向行为例子：
- DIREX-A000000000000001: 成员撤回本人待审核申请
- DIREX-A000000000000002: 撤回他人申请被拒绝
- DIREX-A000000000000003: 重复撤回幂等
- DIREX-A000000000000004: 并发撤回与审批
- DIREX-A000000000000005: 查询实际状态
"""

import os
import sys

import pytest

# 将 src/ 目录加入搜索路径，使 application 包可被导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "src"))

from application.domain import Application, ApplicationStatus, WithdrawalResult
from application.service import MemberService


@pytest.fixture
def service() -> MemberService:
    """创建一个包含测试申请的成员服务实例。"""
    svc = MemberService()
    return svc


def _make_pending_application(
    service: MemberService, owner_id: str = "member-001"
) -> Application:
    """辅助方法：创建并注册一份待审核申请。"""
    app = Application.create(owner_member_id=owner_id)
    service.register_application(app)
    return app


class TestMemberWithdrawsOwnPendingApplication:
    """DIREX-A000000000000001: 成员撤回本人待审核申请。

    Given: 成员已认证，成员有一份待审核的本人申请
    When:  成员请求撤回该申请
    Then:  申请状态变为已撤回，产生一条审计记录（操作者、待审核→已撤回、撤回）
    """

    def test_member_withdraws_own_pending_application(
        self, service: MemberService
    ) -> None:
        # Given
        app = _make_pending_application(service, owner_id="member-001")
        assert app.status == ApplicationStatus.PENDING

        # When
        response = service.withdraw(
            authenticated_member_id="member-001",
            application_id=app.application_id,
        )

        # Then: 申请状态变为已撤回
        assert response.result == WithdrawalResult.SUCCESS
        assert response.current_status == ApplicationStatus.WITHDRAWN
        assert app.status == ApplicationStatus.WITHDRAWN

        # Then: 产生一条审计记录
        audit_entries = service.audit_log.entries_for(app.application_id)
        assert len(audit_entries) == 1
        entry = audit_entries[0]
        assert entry.operator_member_id == "member-001"
        assert entry.previous_status == ApplicationStatus.PENDING
        assert entry.new_status == ApplicationStatus.WITHDRAWN
        assert entry.action == "撤回"


class TestWithdrawOtherMemberApplicationRejected:
    """DIREX-A000000000000002: 撤回他人申请被拒绝。

    Given: 成员已认证，申请不属于该成员
    When:  成员请求撤回该申请
    Then:  撤回被拒绝，申请状态不变，不产生审计记录
    """

    def test_withdraw_other_member_application_rejected(
        self, service: MemberService
    ) -> None:
        # Given: 申请属于 member-001
        app = _make_pending_application(service, owner_id="member-001")
        original_status = app.status

        # When: member-002 尝试撤回
        response = service.withdraw(
            authenticated_member_id="member-002",
            application_id=app.application_id,
        )

        # Then: 撤回被拒绝
        assert response.result == WithdrawalResult.NOT_OWNER

        # Then: 申请状态不变
        assert app.status == original_status

        # Then: 不产生审计记录
        audit_entries = service.audit_log.entries_for(app.application_id)
        assert len(audit_entries) == 0


class TestRepeatedWithdrawalIdempotent:
    """DIREX-A000000000000003: 重复撤回幂等。

    Given: 申请已处于已撤回状态
    When:  成员再次撤回该申请
    Then:  返回已撤回结果，不新增审计记录
    """

    def test_repeated_withdrawal_idempotent(self, service: MemberService) -> None:
        # Given: 先成功撤回一次
        app = _make_pending_application(service, owner_id="member-001")
        first_response = service.withdraw(
            authenticated_member_id="member-001",
            application_id=app.application_id,
        )
        assert first_response.result == WithdrawalResult.SUCCESS
        assert app.status == ApplicationStatus.WITHDRAWN

        audit_count_after_first = len(
            service.audit_log.entries_for(app.application_id)
        )
        assert audit_count_after_first == 1

        # When: 再次撤回
        second_response = service.withdraw(
            authenticated_member_id="member-001",
            application_id=app.application_id,
        )

        # Then: 返回已撤回结果
        assert second_response.result == WithdrawalResult.ALREADY_WITHDRAWN
        assert second_response.current_status == ApplicationStatus.WITHDRAWN

        # Then: 不新增审计记录
        audit_count_after_second = len(
            service.audit_log.entries_for(app.application_id)
        )
        assert audit_count_after_second == audit_count_after_first


class TestConcurrentWithdrawalAndApproval:
    """DIREX-A000000000000004: 并发撤回与审批。

    Given: 申请处于待审核状态
    When:  成员撤回和负责人审批同时发生
    Then:  只有一个操作成功，另一个被拒绝
    """

    def test_concurrent_withdrawal_and_approval(
        self, service: MemberService
    ) -> None:
        # Given
        app = _make_pending_application(service, owner_id="member-001")
        assert app.status == ApplicationStatus.PENDING

        # 模拟并发：两方同时读取当前版本
        version_seen_by_member = app.version
        version_seen_by_approver = app.version

        # When: 成员先执行撤回（使用读到的版本）
        withdraw_succeeded = app.withdraw(version_seen_by_member)

        # When: 审批者尝试使用旧版本审批
        approve_succeeded = app.approve(version_seen_by_approver)

        # Then: 只有一个操作成功
        assert withdraw_succeeded is True
        assert approve_succeeded is False
        assert app.status == ApplicationStatus.WITHDRAWN

        # 反方向场景验证：如果审批者先执行
        app2 = _make_pending_application(service, owner_id="member-001")
        version_a = app2.version
        version_b = app2.version

        # 审批者先执行
        approve_first = app2.approve(version_a)
        # 成员再撤回
        withdraw_second = app2.withdraw(version_b)

        assert approve_first is True
        assert withdraw_second is False
        assert app2.status == ApplicationStatus.APPROVED


class TestQueryActualStatusAfterLostResponse:
    """DIREX-A000000000000005: 查询实际状态。

    Given: 成员之前发起撤回但未收到响应
    When:  成员查询申请状态
    Then:  返回申请的实际当前状态
    """

    def test_query_actual_status_after_lost_response(
        self, service: MemberService
    ) -> None:
        # Given: 创建并撤回一份申请（模拟"已发起撤回但未收到响应"）
        app = _make_pending_application(service, owner_id="member-001")
        service.withdraw(
            authenticated_member_id="member-001",
            application_id=app.application_id,
        )

        # When: 成员查询申请状态
        actual_status = service.query_status(app.application_id)

        # Then: 返回实际当前状态
        assert actual_status == ApplicationStatus.WITHDRAWN

    def test_query_status_of_pending_application(
        self, service: MemberService
    ) -> None:
        """查询未撤回申请的状态也应返回实际状态。"""
        app = _make_pending_application(service, owner_id="member-001")

        actual_status = service.query_status(app.application_id)

        assert actual_status == ApplicationStatus.PENDING
