"""Centralized environment loading for deployment.

All runtime modules should read environment variables after calling
``load_repo_env`` so local runs consistently use the repository root ``.env``.
Platform-provided variables still win because ``override`` defaults to false.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def repo_root() -> Path:
    """Return the repository root that owns the shared .env file."""
    return Path(__file__).resolve().parents[1]


def load_repo_env(*, override: bool = False) -> Path:
    """Load the repository root .env and return its path."""
    env_path = repo_root() / ".env"
    load_dotenv(env_path, override=override)
    return env_path
