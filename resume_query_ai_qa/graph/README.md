# Graph Package

`graph` owns the LangGraph wiring for Query-AI. It coordinates nodes, records route decisions through `state`, and returns the final `ResumeQAState`.

## Files

| File | Responsibility |
| --- | --- |
| `runner.py` | Public `run()` entrypoint, run initialization, final trace persistence. |
| `state.py` | Internal graph state type and initial state construction. |
| `build.py` | LangGraph node registration, edges, and conditional edges. |
| `nodes.py` | Thin graph wrappers around node package APIs. |
| `routes.py` | Conditional edge decisions and route trace recording. |
| `trace_logging.py` | Node decision logging payloads and graph-local summaries. |
| `utils.py` | Small graph-only helpers. |

## Boundaries

- Graph may import node package APIs and state trace helpers.
- Graph must not import `tools`, `scoring`, or `core.data_access`.
- Graph wrappers should move data between graph state and `ResumeQAState`; business rules belong in `core` or the owning node.
- Route functions should only choose the next node and record the route reason.
