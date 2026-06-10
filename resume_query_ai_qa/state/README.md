# State Package

`state` owns context handoff and trace mutation. It is the only package that should append trace events or build the updated session context.

## Files

| File | Responsibility |
| --- | --- |
| `trace.py` | Run, node, route, state snapshot, and run error trace events. |
| `session_context.py` | Builds `updated_session_context` from the completed QA state. |

## Boundaries

- State may inspect `ResumeQAState` and emit observability events.
- State does not decide graph routes, call tools, or generate answers.
- Nodes and graph should call state helpers instead of mutating trace event lists directly.
- Session context writes happen at terminal graph time through `build_updated_session_context`.
