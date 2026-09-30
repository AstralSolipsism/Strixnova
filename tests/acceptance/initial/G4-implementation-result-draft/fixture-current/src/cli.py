"""本地终端CLI入口。

通过命令行完成撤回操作和状态查询，不通过网页或网络服务。
"""

from __future__ import annotations

import argparse
import sys

from application.domain import WithdrawalResult
from application.service import MemberService


def build_parser() -> argparse.ArgumentParser:
    """构建CLI参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="appointment-tool",
        description="预约申请工具 — 本地终端交互",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # 撤回命令
    withdraw_parser = subparsers.add_parser("withdraw", help="撤回本人待审核的预约申请")
    withdraw_parser.add_argument(
        "--member-id", required=True, help="已认证的成员身份"
    )
    withdraw_parser.add_argument(
        "--application-id", required=True, help="要撤回的申请身份"
    )

    # 状态查询命令
    status_parser = subparsers.add_parser("status", help="查询申请的当前状态")
    status_parser.add_argument(
        "--application-id", required=True, help="要查询的申请身份"
    )

    return parser


def run_cli(service: MemberService, argv: list[str] | None = None) -> int:
    """执行CLI命令。

    Args:
        service: 成员服务实例。
        argv: 命令行参数（默认从 sys.argv 读取）。

    Returns:
        退出码：0 成功，1 操作被拒绝或失败。
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "withdraw":
        response = service.withdraw(
            authenticated_member_id=args.member_id,
            application_id=args.application_id,
        )
        if response.result == WithdrawalResult.SUCCESS:
            print(f"已撤回申请 {response.application_id}")
            return 0
        elif response.result == WithdrawalResult.ALREADY_WITHDRAWN:
            print(f"申请 {response.application_id} 已处于已撤回状态")
            return 0
        elif response.result == WithdrawalResult.NOT_OWNER:
            print(f"拒绝：无权撤回申请 {response.application_id}")
            return 1
        elif response.result == WithdrawalResult.INVALID_STATUS:
            print(
                f"拒绝：申请 {response.application_id} "
                f"当前状态为{response.current_status.value}，不可撤回"
            )
            return 1
        elif response.result == WithdrawalResult.CONFLICT:
            print(f"冲突：申请 {response.application_id} 已被其他操作修改")
            return 1

    elif args.command == "status":
        status = service.query_status(application_id=args.application_id)
        if status is None:
            print(f"申请 {args.application_id} 不存在")
            return 1
        print(f"申请 {args.application_id} 当前状态：{status.value}")
        return 0

    return 1
