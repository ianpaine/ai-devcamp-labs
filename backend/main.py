"""AG-UI bridge: exposes the social_poster agent to the CopilotKit frontend.

Run from the repo root:  uv run uvicorn backend.main:app --port 8000
"""

import os
import pathlib
import re

from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google.adk.memory import VertexAiMemoryBankService
from google.adk.sessions import VertexAiSessionService

load_dotenv(pathlib.Path(__file__).parent / "social_poster" / ".env")

from backend.social_poster import db  # noqa: E402  (needs .env first)
from backend.social_poster.agent import root_agent  # noqa: E402  (needs .env first)

app = FastAPI(title="social-agent AG-UI backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_engine_details() -> dict[str, str] | None:
    """Parses project, location, and engine ID from APP_URL if running on Agent Runtime.

    APP_URL is injected by Agent Runtime and carries the engine's full resource name:
    projects/{project}/locations/{location}/reasoningEngines/{engine_id}

    We parse project, location, and engine ID directly from APP_URL rather than
    relying on GOOGLE_CLOUD_LOCATION or GOOGLE_CLOUD_PROJECT:
    - GOOGLE_CLOUD_LOCATION is set to 'global' (optimal for Gemini models), but the
      engine, its sessions, and its Memory Bank live regionally (e.g. us-central1).
      Querying 'global' would fail to find the engine.
    - GOOGLE_CLOUD_PROJECT in the container holds the numeric project number; parsing
      APP_URL guarantees the exact project and location that match the deployed engine.
    """
    app_url = os.environ.get("APP_URL")
    if not app_url:
        return None
    match = re.search(
        r"projects/(?P<project>[^/]+)/locations/(?P<location>[^/]+)/reasoningEngines/(?P<engine_id>[^/]+)",
        app_url,
    )
    if not match:
        raise ValueError(
            f"Failed to parse Agent Runtime engine resource name from APP_URL: {app_url}"
        )
    return {
        "project": match.group("project"),
        "location": match.group("location"),
        "agent_engine_id": match.group("engine_id"),
    }


def _resolve_session_service() -> VertexAiSessionService | None:
    """Uses VertexAiSessionService on Agent Runtime, or in-memory default locally."""
    details = _parse_engine_details()
    return VertexAiSessionService(**details) if details else None


def _resolve_memory_service() -> VertexAiMemoryBankService | None:
    """Uses VertexAiMemoryBankService on Agent Runtime, or in-memory default locally."""
    details = _parse_engine_details()
    return VertexAiMemoryBankService(**details) if details else None


adk_agent = ADKAgent(
    adk_agent=root_agent,
    app_name="social_poster",
    user_id="devcamp-user",  # single-user POC; extract from auth in real apps
    session_service=_resolve_session_service(),
    memory_service=_resolve_memory_service(),
)

add_adk_fastapi_endpoint(app, adk_agent, path="/api/adk")

# Serve generate_image's output files so the frontend's image gallery
# (PostGallery.tsx) can render them — tools.py writes local file paths, which
# the browser has no way to read directly otherwise.
GALLERY_DIR = pathlib.Path(__file__).resolve().parents[1] / "gallery"
GALLERY_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=GALLERY_DIR), name="outputs")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/posts")
def posts() -> dict:
    """Published posts (with whatever image they used), read from the local
    SQLite store — durable across reloads/restarts, unlike ADK session state
    or the browser's own chat history."""
    return {"posts": db.list_posts()}
