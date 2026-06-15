"""Stable public exports for state helpers.

这个包只公开 trace mutation 和 session context handoff helper。
上层 graph 应通过这里调用 state 能力，避免直接散落修改 qa.trace。
"""

from .session_context import build_updated_session_context
from .trace import finalize_run_trace, record_node_decision, record_route_decision, record_run_error, record_run_start, record_state_snapshot

__all__ = [
    "build_updated_session_context",
    "finalize_run_trace",
    "record_node_decision",
    "record_route_decision",
    "record_run_error",
    "record_run_start",
    "record_state_snapshot",
]
