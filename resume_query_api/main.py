from __future__ import annotations

import os
import secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from resume_query_common.env import load_repo_env

from .routes.candidates import router as candidates_router
from .routes.health import router as health_router
from .routes.ingestion import router as ingestion_router
from .routes.qa import router as qa_router

load_repo_env()


def _allowed_origins() -> list[str]:
    configured = os.getenv("RESUME_API_ALLOWED_ORIGINS", "").strip()
    if configured:
        return [item.strip() for item in configured.split(",") if item.strip()]
    return [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
    ]


def _request_token(request) -> str:
    authorization = str(request.headers.get("authorization", "") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    header_token = str(request.headers.get("x-resume-app-password", "") or "").strip()
    if header_token:
        return header_token
    return str(request.query_params.get("access_token", "") or "").strip()


def _cors_headers_for_request(request) -> dict[str, str]:
    origin = str(request.headers.get("origin", "") or "").strip()
    if not origin or origin not in set(_allowed_origins()):
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


app = FastAPI(title="Resume Query API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_app_password(request, call_next):
    password = os.getenv("RESUME_APP_PASSWORD", "").strip()
    if (
        password
        and request.method.upper() != "OPTIONS"
        and request.url.path != "/health"
        and not secrets.compare_digest(_request_token(request), password)
    ):
        return JSONResponse(
            {"detail": "访问密码无效或缺失。"},
            status_code=401,
            headers=_cors_headers_for_request(request),
        )
    return await call_next(request)


@app.middleware("http")
async def add_no_store_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


app.include_router(health_router)
app.include_router(candidates_router)
app.include_router(ingestion_router)
app.include_router(qa_router)


def create_app() -> FastAPI:
    return app
