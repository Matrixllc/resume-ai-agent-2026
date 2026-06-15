"""Human-readable Query-AI log browser.

这个文件负责什么：
  读取 observability 写出的 qa_runs.jsonl 和 detail JSON，渲染成列表/详情视图。

应该从哪个函数读起：
  main() -> list_views()/find_detail() -> build_run_view() -> render_list()/render_show()。

不会负责什么：
  不修改日志，不重新判断业务对错，不修复 plan/result/answer。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

DEFAULT_LOGS_DIR = Path(__file__).resolve().parents[1] / "logs"


def load_run_summaries(logs_dir: Path = DEFAULT_LOGS_DIR) -> list[dict[str, Any]]:
    """读取 qa_runs.jsonl，返回按文件顺序排列的 run summary。"""
    path = Path(logs_dir) / "qa_runs.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def find_detail(trace_id: str, logs_dir: Path = DEFAULT_LOGS_DIR) -> dict[str, Any]:
    """按 trace_id 找到最新 detail JSON 并解析。"""
    matches = sorted(Path(logs_dir).glob(f"*_{trace_id}.json"))
    if not matches:
        return {}
    value = json.loads(matches[-1].read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def build_run_view(summary: dict[str, Any], detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """把 summary/detail 合并成 CLI 展示用的稳定 view。"""
    detail = detail or {}
    timeline = _timeline(detail)
    fallbacks = [
        {
            "node": str(item.get("node") or ""),
            "reason": _short_reason(item.get("fallback_reason")),
            "category": _fallback_category(item.get("fallback_reason")),
        }
        for item in timeline
        if item.get("fallback_reason")
    ]
    repairs = [
        {
            "node": str(item.get("node") or ""),
            "action": str(item.get("repair_action") or ""),
            "category": str(item.get("error_category") or ""),
        }
        for item in timeline
        if item.get("repair_action")
    ]
    validator_errors = _validator_errors(detail)
    warnings = _warnings(detail)
    status = str(summary.get("final_status") or "unknown")
    failed_node = str(summary.get("failed_at_node") or dict(detail.get("failed_at") or {}).get("node") or "")
    failed_reason = _short_reason(summary.get("failed_reason") or dict(detail.get("failed_at") or {}).get("reason"))
    return {
        "trace_id": str(summary.get("trace_id") or ""),
        "created_at": str(summary.get("created_at") or ""),
        "question": str(summary.get("question") or ""),
        "status": status,
        "intent": str(summary.get("intent") or ""),
        "duration_ms": _duration_ms(timeline),
        "path": str(summary.get("path_preview") or ""),
        "tools": list(summary.get("tool_result_status") or []),
        "warnings": warnings,
        "fallbacks": fallbacks,
        "repairs": repairs,
        "validator_errors": validator_errors,
        "failed_node": failed_node,
        "failed_reason": failed_reason,
        "answer": str(dict(detail.get("final_answer") or {}).get("text") or summary.get("answer_preview") or ""),
        "what_happened": _what_happened(status, failed_node, fallbacks, repairs, warnings),
        "system_handling": _system_handling(status, fallbacks, repairs),
        "impact": _impact(status, fallbacks, repairs),
        "suggested_check": _suggested_check(failed_node, fallbacks, repairs, validator_errors),
    }


def list_views(
    mode: str = "list",
    *,
    logs_dir: Path = DEFAULT_LOGS_DIR,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """按模式列出最近运行、失败运行或 fallback/repair 运行。"""
    output: list[dict[str, Any]] = []
    for summary in reversed(load_run_summaries(logs_dir)):
        detail = find_detail(str(summary.get("trace_id") or ""), logs_dir)
        view = build_run_view(summary, detail)
        if mode == "failures" and view["status"] not in {"failed", "needs_clarification"}:
            continue
        if mode == "fallbacks" and not view["fallbacks"] and not view["repairs"]:
            continue
        output.append(view)
        if len(output) >= limit:
            break
    return output


def render_list(views: Iterable[dict[str, Any]]) -> str:
    """把多个 run view 渲染成紧凑列表文本。"""
    rows = list(views)
    if not rows:
        return "没有匹配的 Query-AI 运行日志。"
    lines = ["时间 | 状态 | intent | fallback/repair | trace_id | 问题"]
    for view in rows:
        marker = f"{len(view['fallbacks'])}/{len(view['repairs'])}"
        lines.append(
            f"{view['created_at']} | {view['status']} | {view['intent']} | {marker} | "
            f"{view['trace_id']} | {_preview(view['question'], 50)}"
        )
    return "\n".join(lines)


def render_show(view: dict[str, Any]) -> str:
    """把单个 run view 渲染成人类可读详情文本。"""
    if not view:
        return "未找到该 trace_id 对应的 Query-AI 日志。"
    lines = [
        f"Trace ID: {view['trace_id']}",
        f"问题: {view['question']}",
        f"状态: {view['status']} | intent: {view['intent']} | 耗时: {view['duration_ms']} ms",
        "",
        f"发生了什么: {view['what_happened']}",
        f"系统如何处理: {view['system_handling']}",
        f"影响: {view['impact']}",
        f"建议优先检查: {view['suggested_check']}",
        "",
        f"执行路径: {view['path'] or '未记录'}",
    ]
    if view["tools"]:
        lines.append("工具结果:")
        for item in view["tools"]:
            count = f", count={item.get('result_count')}" if item.get("result_count") is not None else ""
            lines.append(f"- {item.get('tool')}: {item.get('status')} ({item.get('result_shape', 'unknown')}{count})")
    if view["fallbacks"]:
        lines.append("Fallback:")
        lines.extend(f"- {item['node']} [{item['category']}]: {item['reason']}" for item in view["fallbacks"])
    if view["repairs"]:
        lines.append("Repair:")
        lines.extend(f"- {item['node']}: {item['action']} ({item['category'] or '未分类'})" for item in view["repairs"])
    if view["warnings"]:
        lines.append("Warnings:")
        lines.extend(f"- {_short_reason(item)}" for item in view["warnings"])
    if view["validator_errors"]:
        lines.append("Validator errors:")
        for layer, errors in view["validator_errors"].items():
            lines.extend(f"- {layer}: {_short_reason(error)}" for error in errors)
    if view["answer"]:
        lines.extend(["", "最终答案:", view["answer"]])
    return "\n".join(lines)


def _validator_errors(detail: dict[str, Any]) -> dict[str, list[str]]:
    """获取校验器错误集合并返回。"""
    debug = dict(detail.get("debug_refs") or {})
    output: dict[str, list[str]] = {}
    for layer, key in (
        ("plan", "plan_validation_errors"),
        ("execution", "execution_validation_errors"),
        ("answer", "answer_validation_errors"),
    ):
        values = list(debug.get(key) or [])
        if not values:
            values = _errors_from_steps(detail, f"{layer}_validator")
        if values:
            output[layer] = [str(item) for item in values]
    return output


def _errors_from_steps(detail: dict[str, Any], node: str) -> list[str]:
    """从步骤集合提取错误集合并返回。"""
    for item in detail.get("decision_log") or []:
        if item.get("node") == node:
            return [str(value) for value in dict(item.get("output") or {}).get("errors") or []]
    for step in detail.get("node_steps") or []:
        if step.get("node") == node:
            return [str(item) for item in dict(step.get("details") or {}).get("errors") or []]
    return []


def _warnings(detail: dict[str, Any]) -> list[str]:
    """获取警告集合并返回。"""
    output: list[str] = []
    for item in [*_timeline(detail), *(detail.get("execution_path") or [])]:
        for warning in item.get("warnings") or []:
            value = str(warning)
            if value not in output:
                output.append(value)
    return output


def _timeline(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """从 detail 中提取节点时间线，优先使用 decision_log。"""
    if detail.get("decision_log"):
        rows: list[dict[str, Any]] = []
        for item in detail.get("decision_log") or []:
            output = dict(item.get("output") or {})
            rows.append(
                {
                    "node": item.get("node", ""),
                    "engine": item.get("engine", ""),
                    "duration_ms": item.get("duration_ms"),
                    "fallback_reason": item.get("fallback_reason", ""),
                    "repair_action": output.get("repair_action", ""),
                    "error_category": output.get("error_category", ""),
                    "errors": output.get("errors", []),
                    "warnings": output.get("warnings", []),
                }
            )
        return rows
    return list(detail.get("node_timeline") or [])


def _duration_ms(timeline: list[dict[str, Any]]) -> float:
    """获取耗时毫秒并返回。"""
    return round(sum(float(item.get("duration_ms") or 0) for item in timeline), 2)


def _what_happened(status: str, failed_node: str, fallbacks: list[dict[str, str]], repairs: list[dict[str, str]], warnings: list[str]) -> str:
    """根据状态、fallback、repair 和 warning 生成一句运行概览。"""
    if status in {"failed", "needs_clarification"}:
        return f"查询未正常完成，停止在 {failed_node or '未知节点'}。"
    if fallbacks or repairs:
        return "查询已完成，但中间发生了 fallback 或 repair。"
    if warnings:
        return "查询已完成，并产生了可解释 warning。"
    return "查询已完成，主链未记录失败、fallback 或 repair。"


def _system_handling(status: str, fallbacks: list[dict[str, str]], repairs: list[dict[str, str]]) -> str:
    """描述系统如何处理失败、repair 或 fallback。"""
    if status in {"failed", "needs_clarification"}:
        return "系统保留错误和路由信息，没有静默生成未经校验的答案。"
    if repairs:
        return "系统执行 repair 后重新进入 validator。"
    if fallbacks:
        return "系统丢弃不可用输出，并使用受控 fallback 继续完成查询。"
    return "系统按正常路径完成工具执行、答案生成和校验。"


def _impact(status: str, fallbacks: list[dict[str, str]], repairs: list[dict[str, str]]) -> str:
    """描述该运行状态对最终答案可信度的影响。"""
    if status in {"failed", "needs_clarification"}:
        return "本轮没有生成可作为最终结果使用的已校验答案。"
    if fallbacks or repairs:
        return "最终答案已重新通过 validator；中间输出未直接交付。"
    return "未发现影响最终答案可信度的问题。"


def _suggested_check(
    failed_node: str,
    fallbacks: list[dict[str, str]],
    repairs: list[dict[str, str]],
    validator_errors: dict[str, list[str]],
) -> str:
    """根据失败层和校验错误，给出优先排查方向。"""
    node = failed_node or (fallbacks[-1]["node"] if fallbacks else "") or (repairs[-1]["node"] if repairs else "")
    if "plan" in validator_errors or node in {"router", "condition_normalizer", "execution_policy", "planner", "plan_compiler", "plan_validator", "plan_repair"}:
        return "router/plan compiler/plan validator，以及 intents、router_rules、compiler_templates、tool_policy 配置。"
    if "execution" in validator_errors or node in {"executor", "execution_validator", "execution_repair"}:
        return "工具参数、工具返回结果、候选池 lineage 和 execution validator。"
    if "answer" in validator_errors or node in {"aggregator", "answer_validator", "answer_rewrite", "rule_answer_fallback"}:
        return "aggregator grounded context、answer layout、claims 和 answer validator。"
    return "对应节点的 decision_log、route_events 和相关 README。"


def _short_reason(value: Any, limit: int = 180) -> str:
    """压缩错误、warning 或 fallback reason，避免 CLI 输出过长。"""
    text = " ".join(str(value or "").split())
    return _preview(text, limit) or "未记录原因"


def _fallback_category(value: Any) -> str:
    """根据 fallback reason 文本粗分兜底类别。"""
    text = str(value or "").lower()
    if "rule" in text or "deterministic" in text:
        return "规则回退"
    if "unknown_candidate" in text or "drift" in text or "rejected" in text:
        return "输出漂移拒绝"
    if "error" in text or "timeout" in text or "unavailable" in text or "connection" in text:
        return "LLM/系统异常回退"
    return "其他回退"


def _preview(value: str, limit: int) -> str:
    """生成定长文本预览。"""
    return value if len(value) <= limit else value[:limit].rstrip() + "..."


def _build_parser() -> argparse.ArgumentParser:
    """构建参数解析器并返回。"""
    parser = argparse.ArgumentParser(description="Query-AI 人类可读日志查询工具")
    parser.add_argument("command", choices=["list", "show", "failures", "fallbacks"])
    parser.add_argument("trace_id", nargs="?")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--logs-dir", type=Path, default=DEFAULT_LOGS_DIR)
    return parser


def main() -> int:
    """解析命令行参数并执行主流程。"""
    args = _build_parser().parse_args()
    if args.command == "show":
        if not args.trace_id:
            raise SystemExit("show 命令需要 trace_id")
        detail = find_detail(args.trace_id, args.logs_dir)
        summary = dict(detail.get("run_summary") or {})
        view = build_run_view(summary, detail) if summary else {}
        print(json.dumps(view, ensure_ascii=False, indent=2) if args.json_output else render_show(view))
        return 0 if view else 1
    views = list_views(args.command, logs_dir=args.logs_dir, limit=max(1, args.limit))
    print(json.dumps(views, ensure_ascii=False, indent=2) if args.json_output else render_list(views))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
