"""Unit tests for backend/main.py session and memory service resolution."""

import pytest
from google.adk.memory import VertexAiMemoryBankService
from google.adk.sessions import VertexAiSessionService

from backend.main import _resolve_memory_service, _resolve_session_service
from backend.social_poster.agent import _TOOL_STAGES


def test_resolve_session_service_local(monkeypatch):
    monkeypatch.delenv("APP_URL", raising=False)
    service = _resolve_session_service()
    assert service is None


def test_resolve_memory_service_local(monkeypatch):
    monkeypatch.delenv("APP_URL", raising=False)
    service = _resolve_memory_service()
    assert service is None


def test_resolve_session_service_agent_runtime_resource_name(monkeypatch):
    monkeypatch.setenv(
        "APP_URL",
        "projects/test-project/locations/us-central1/reasoningEngines/1234567890",
    )
    service = _resolve_session_service()
    assert isinstance(service, VertexAiSessionService)
    assert service._project == "test-project"
    assert service._location == "us-central1"
    assert service._agent_engine_id == "1234567890"


def test_resolve_memory_service_agent_runtime_resource_name(monkeypatch):
    monkeypatch.setenv(
        "APP_URL",
        "projects/test-project/locations/us-central1/reasoningEngines/1234567890",
    )
    service = _resolve_memory_service()
    assert isinstance(service, VertexAiMemoryBankService)
    assert service._project == "test-project"
    assert service._location == "us-central1"
    assert service._agent_engine_id == "1234567890"


def test_resolve_session_service_agent_runtime_url(monkeypatch):
    monkeypatch.setenv(
        "APP_URL",
        "https://us-central1-aiplatform.googleapis.com/reasoningEngines/v1/projects/my-p/locations/us-central1/reasoningEngines/engine-xyz/api",
    )
    service = _resolve_session_service()
    assert isinstance(service, VertexAiSessionService)
    assert service._project == "my-p"
    assert service._location == "us-central1"
    assert service._agent_engine_id == "engine-xyz"


def test_resolve_memory_service_agent_runtime_url(monkeypatch):
    monkeypatch.setenv(
        "APP_URL",
        "https://us-central1-aiplatform.googleapis.com/reasoningEngines/v1/projects/my-p/locations/us-central1/reasoningEngines/engine-xyz/api",
    )
    service = _resolve_memory_service()
    assert isinstance(service, VertexAiMemoryBankService)
    assert service._project == "my-p"
    assert service._location == "us-central1"
    assert service._agent_engine_id == "engine-xyz"


def test_resolve_session_service_invalid_app_url(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://example.com/invalid/url")
    with pytest.raises(ValueError, match="Failed to parse Agent Runtime engine resource name"):
        _resolve_session_service()


def test_tool_stages_maps_load_memory_to_consulting_memory():
    assert "load_memory" in _TOOL_STAGES
    assert _TOOL_STAGES["load_memory"] == "consulting_memory"
