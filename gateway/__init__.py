"""
Gateway module for external messaging interfaces and human-in-the-loop approvals.
"""

from gateway.bot import (
    build_telegram_application,
    handle_callback_query,
    send_approval_request,
)

__all__ = [
    "send_approval_request",
    "build_telegram_application",
    "handle_callback_query",
]