"""Router node package.

对外仍暴露 `route_question` 和 `route_question_llm`；内部拆成 node/rules/
guard/finalizer，方便阅读“问题如何变成 RouterOutput 协议”。
"""

from .node import route_question, route_question_llm

__all__ = ["route_question", "route_question_llm"]
