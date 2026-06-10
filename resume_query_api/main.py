from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes.candidates import router as candidates_router
from .routes.health import router as health_router
from .routes.ingestion import router as ingestion_router
from .routes.qa import router as qa_router

app = FastAPI(title="Resume Query API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
