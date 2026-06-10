# Observability Package

`observability` owns log sinks and persisted run artifacts. It receives trace data from `state` and writes structured files under `logs/`.

## Log Outputs

| File | Responsibility |
| --- | --- |
| `query_ai_events.jsonl` | Atomic event stream for run/node/route/state events. Good for tailing live behavior. |
| `qa_runs.jsonl` | One compact summary row per graph run. Good for finding a trace id quickly. |
| `<timestamp>_<trace_id>.json` | Full detail for one run, including node steps, route events, `execution_path`, `node_timeline`, and `failed_at`. |

## Boundaries

- Observability writes files and formats persisted debug views.
- It does not decide node behavior, route decisions, or session context.
- Large raw tool payloads should be summarized before logging.
- Trace mutation remains in `state`; observability serializes the trace.
