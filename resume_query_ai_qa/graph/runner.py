"""Public runner for one Query-AI graph invocation.

这个文件负责什么：
  初始化 config/logging/graph/state，执行 LangGraph，并在结束后持久化 trace。

应该从哪个函数读起：
  run()。

不会负责什么：
  不直接调用业务 node API，不做 route 判断，不解释 YAML 业务字段。
"""

from __future__ import annotations

import uuid

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.schemas import ResumeQAState
from resume_query_ai_qa.observability import configure_query_ai_logging, write_run_log
from resume_query_ai_qa.state import finalize_run_trace, record_run_error, record_run_start

from .build import build_state_graph
from .state import build_initial_state


def run(
    question: str,
    session_context: dict | None = None,
    *,
    use_llm: bool = True,
    max_plan_repairs: int = 2,
    max_execution_repairs: int = 2,
    max_answer_rewrites: int = 1,
    debug_trace: bool = False,
    config: ResumeQAConfig | None = None,
) -> ResumeQAState:
    """执行一次问答 graph，并返回最终 ResumeQAState。

    retry 参数会进入 graph state，routes.py 用它们判断 repair/rewrite 是否还能继续。
    """
    cfg = config or load_config()
    configure_query_ai_logging(cfg)
    graph = build_state_graph()
    initial = build_initial_state(
        question,
        session_context,
        use_llm=use_llm,
        max_plan_repairs=max_plan_repairs,
        max_execution_repairs=max_execution_repairs,
        max_answer_rewrites=max_answer_rewrites,
        config=cfg,
    )
    initial["qa"].trace.trace_id = uuid.uuid4().hex
    initial["qa"].trace.deep_debug = debug_trace
    record_run_start(initial["qa"], cfg)
    try:
        result = graph.invoke(initial)
    except Exception as error:
        record_run_error(initial["qa"], error, config=cfg)
        raise
    qa = result["qa"]
    final_status = str(result.get("final_status") or "failed")
    qa.trace.final_status = final_status if final_status in {"ok", "failed", "needs_clarification"} else "failed"
    finalize_run_trace(qa, config=cfg)
    write_run_log(qa, cfg)
    return qa
