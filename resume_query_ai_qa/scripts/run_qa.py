"""Run one Query-AI graph turn from the command line.

这个文件负责什么：
  解析 CLI 参数，调用 graph.run，并把 answer / trace / state 打印出来。

应该从哪个函数读起：
  main() -> _parse_session_context()。

不会负责什么：
  不解释 intent，不选择工具，不修改 graph 行为，不替代 benchmark。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resume_query_ai_qa.graph import run


def main() -> None:
    """解析命令行参数，运行 graph，并按输出模式打印结果。"""
    parser = argparse.ArgumentParser(description="Run the resume QA graph.")
    parser.add_argument("question", help="User question to send through the QA graph.")
    parser.add_argument(
        "--session-context-json",
        default="{}",
        help="Optional JSON object with prior session context.",
    )
    parser.add_argument(
        "--answer-only",
        action="store_true",
        help="Print only the final answer text instead of the full debug state.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM router/planner/aggregator and use deterministic rules only.",
    )
    parser.add_argument(
        "--debug-json",
        action="store_true",
        help="Print the full debug state as JSON.",
    )
    parser.add_argument(
        "--show-trace",
        action="store_true",
        help="Print only the trace JSON.",
    )
    args = parser.parse_args()
    session_context = _parse_session_context(args.session_context_json)
    state = run(args.question, session_context=session_context, use_llm=not args.no_llm)
    if args.show_trace:
        print(state.trace.model_dump_json(indent=2, ensure_ascii=False))
        return
    if args.answer_only:
        print(state.answer.answer if state.answer else "")
        return
    if args.debug_json:
        print(state.model_dump_json(indent=2, ensure_ascii=False))
        return
    print(state.model_dump_json(indent=2, ensure_ascii=False))


def _parse_session_context(raw: str) -> dict[str, Any]:
    """把 CLI 传入的 JSON 字符串解析为 session_context dict。"""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"session context must be valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise SystemExit("session context must be a JSON object")
    return payload


if __name__ == "__main__":
    main()
