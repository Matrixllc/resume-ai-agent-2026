"""Static contracts that keep business rules in configuration."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    """运行静态架构合同，发现边界回退时集中报告并退出失败。"""
    errors: list[str] = []
    _reject_duplicate_taxonomy(errors)
    _reject_local_rule_constants(errors)
    _reject_repair_message_routing(errors)
    _reject_cross_layer_imports(errors)
    _reject_compatibility_wrapper_dependencies(errors)
    _reject_placeholder_docstrings(errors)
    if errors:
        raise SystemExit("Architecture contract failed:\n" + "\n".join(f"- {item}" for item in errors))
    print("OK: architecture contract benchmark")


def _reject_duplicate_taxonomy(errors: list[str]) -> None:
    """禁止 v3 私自维护领域或概念分类，确保 shared_taxonomy 是唯一真源。"""
    for path in (
        ROOT / "resume_query_v3" / "configs" / "domains",
        ROOT / "resume_query_v3" / "configs" / "concepts",
    ):
        if path.exists() and any(path.glob("*.yaml")):
            errors.append(f"taxonomy must only live under shared_taxonomy: {path}")


def _reject_local_rule_constants(errors: list[str]) -> None:
    """禁止重新引入已经迁移到配置层的本地规则常量。"""
    banned = {
        "_SOURCE_TOOLS",
        "_RETRIEVAL_CONDITION_TYPES",
        "_REFERENCE_RULES",
        "_EVIDENCE_CAPABLE_TOOLS",
        "RULE_REPAIR_CATEGORIES",
    }
    for path in (ROOT / "resume_query_ai_qa").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in banned:
                        errors.append(f"{path.relative_to(ROOT)} defines banned local rule `{target.id}`")


def _reject_repair_message_routing(errors: list[str]) -> None:
    """禁止 repair 根据错误文案做路由，要求使用结构化 ValidationIssue。"""
    forbidden_messages = (
        "candidate_compare_pair requires exactly",
        "returned no candidates",
        "argument binding failed",
        "missing key in argument reference",
    )
    for relative in (
        "resume_query_ai_qa/nodes/execution_repair/node.py",
        "resume_query_ai_qa/nodes/clarification/node.py",
        "resume_query_ai_qa/nodes/answer_rewrite/policy.py",
    ):
        path = ROOT / relative
        source = path.read_text(encoding="utf-8").lower()
        for message in forbidden_messages:
            if message in source:
                errors.append(f"{relative} routes repair/clarification through error text `{message}`")


def _reject_cross_layer_imports(errors: list[str]) -> None:
    """检查核心层和节点层的导入方向，阻止业务规则反向依赖编排层。"""
    forbidden_by_prefix = {
        "resume_query_ai_qa/core": ("resume_query_ai_qa.nodes", "resume_query_ai_qa.graph", "resume_query_ai_qa.tools"),
        "resume_query_ai_qa/nodes": ("resume_query_ai_qa.graph",),
        "resume_query_ai_qa/tools": ("resume_query_ai_qa.graph", "resume_query_ai_qa.nodes"),
        "resume_query_ai_qa/scoring": ("resume_query_ai_qa.graph", "resume_query_ai_qa.nodes"),
    }
    for path in (ROOT / "resume_query_ai_qa").rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        forbidden = next((values for prefix, values in forbidden_by_prefix.items() if relative.startswith(prefix)), ())
        if not forbidden:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            names = [item.name for item in node.names] if isinstance(node, ast.Import) else []
            imported = [module, *names]
            for value in imported:
                if value and any(value == prefix or value.startswith(f"{prefix}.") for prefix in forbidden):
                    errors.append(f"{relative} imports forbidden layer `{value}`")


def _reject_compatibility_wrapper_dependencies(errors: list[str]) -> None:
    """禁止生产代码依赖兼容转发模块，确保真实实现只有一份。"""
    wrapper_modules = (
        "resume_query_ai_qa.nodes.aggregator",
        "resume_query_ai_qa.nodes.plan_compiler.binding",
        "resume_query_ai_qa.nodes.plan_compiler.artifacts",
        "resume_query_ai_qa.nodes.planner.rules",
    )
    allowed_files = {
        "resume_query_ai_qa/nodes/aggregator/__init__.py",
        "resume_query_ai_qa/nodes/aggregator/node.py",
        "resume_query_ai_qa/nodes/plan_compiler/__init__.py",
    }
    for path in (ROOT / "resume_query_ai_qa").rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if relative in allowed_files or "/benchmarks/" in f"/{relative}":
            continue
        source = path.read_text(encoding="utf-8")
        for module in wrapper_modules:
            if module in source:
                errors.append(f"{relative} depends on compatibility wrapper `{module}`")


def _reject_placeholder_docstrings(errors: list[str]) -> None:
    """禁止模板化或中英拼接的函数注释，要求说明实际职责。"""
    placeholders = (
        "作为内部辅助逻辑",
        "作为对外入口逻辑",
        "中文说明：",
        "执行共享规则",
        "保持当前模块的职责边界",
        "为答案生成阶段处理",
        "处理大模型客户端",
        "执行合同检查",
        "不承载生产规则",
        "输出 RouterOutput 草稿或派生字段",
        "实现只读工具的",
    )
    mixed_token = re.compile(
        r"[\u4e00-\u9fff](?:node|run|call|tool|from|for|with|apply|match|validate|"
        r"build|render|resolve|dedupe|normalize|strip|compact|timeline|payload|"
        r"scope|result|context|intent|scenario|workflow|evidence|candidate|fallback|rule)[A-Za-z]*",
        re.IGNORECASE,
    )
    for path in (ROOT / "resume_query_ai_qa").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            doc = ast.get_docstring(node, clean=False) or ""
            if not doc:
                errors.append(f"{path.relative_to(ROOT)}:{node.lineno} `{node.name}` missing docstring")
            elif any(marker in doc for marker in placeholders):
                errors.append(f"{path.relative_to(ROOT)}:{node.lineno} `{node.name}` uses placeholder docstring")
            elif doc.startswith("处理") or mixed_token.search(doc):
                errors.append(f"{path.relative_to(ROOT)}:{node.lineno} `{node.name}` uses unreadable docstring")


if __name__ == "__main__":
    main()
