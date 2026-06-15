"""Deterministic answer renderers grouped by layout/task.

renderers 只格式化 grounded tool facts，不新增事实、不选择工具、不绕过 validator。
"""

from .router import render_rule_answer

__all__ = ["render_rule_answer"]
