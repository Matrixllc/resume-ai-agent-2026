from __future__ import annotations

from fastapi import APIRouter, HTTPException

from resume_query_ai_qa.graph import run

from resume_query_api.qa_response import _response_from_state
from resume_query_api.qa_schemas import QAAskRequest, QAAskResponse
from resume_query_api.qa_trace import _trace_summary  # re-export for benchmark compatibility

router = APIRouter(prefix="/qa", tags=["qa"])


@router.post("/ask", response_model=QAAskResponse)
def ask_resume_qa(request: QAAskRequest, debug: bool | None = None) -> QAAskResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    state = run(
        question,
        session_context=request.session_context,
        use_llm=request.use_llm,
        debug_trace=request.debug if debug is None else debug,
    )
    return _response_from_state(state, debug=request.debug if debug is None else debug)
