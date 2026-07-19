"""Tests for the optional AgentTrace runtime gate."""

from __future__ import annotations

from app import observability
from app.config import settings


class _FakeTrace:
    def __init__(self) -> None:
        self.configure_options = None
        self.flush_timeout = None
        self.agent_calls = 0

    def configure(self, **options):
        self.configure_options = options

    def flush(self, timeout=None):
        self.flush_timeout = timeout

    def agent(self, **_options):
        def decorator(function):
            def wrapper(*args, **kwargs):
                self.agent_calls += 1
                return function(*args, **kwargs)

            return wrapper

        return decorator


class _FailingTrace(_FakeTrace):
    def configure(self, **_options):
        raise OSError("storage unavailable")


def test_agenttrace_decorators_activate_only_after_successful_initialization(
    monkeypatch,
    tmp_path,
):
    fake = _FakeTrace()
    storage_path = tmp_path / "agenttrace.db"
    monkeypatch.setattr(settings, "agenttrace_enabled", True)
    monkeypatch.setattr(settings, "agenttrace_project", "test-conversations")
    monkeypatch.setattr(settings, "agenttrace_storage_url", str(storage_path))
    monkeypatch.setattr(settings, "agenttrace_flush_timeout_seconds", 2.5)
    monkeypatch.setattr(observability, "_trace", fake)
    monkeypatch.setattr(observability, "_initialized", False)

    @observability.trace_agent(name="Test node", node_key="test.node")
    def instrumented(value: int) -> int:
        return value + 1

    # Import-time decoration never enables capture before application startup.
    assert instrumented(1) == 2
    assert fake.agent_calls == 0

    assert observability.initialize_agenttrace() is True
    assert instrumented(2) == 3
    assert fake.agent_calls == 1
    assert fake.configure_options["project"] == "test-conversations"
    assert fake.configure_options["storage_url"] == str(storage_path)
    assert fake.configure_options["strict_mode"] is False
    assert fake.configure_options["redaction"] == {"enabled": True}

    observability.flush_agenttrace()
    assert fake.flush_timeout == 2.5


def test_agenttrace_initialization_failure_keeps_business_function_active(monkeypatch):
    fake = _FailingTrace()
    monkeypatch.setattr(settings, "agenttrace_enabled", True)
    monkeypatch.setattr(observability, "_trace", fake)
    monkeypatch.setattr(observability, "_initialized", False)

    @observability.trace_agent(name="Test node", node_key="test.node")
    def business_function() -> str:
        return "business-result"

    assert observability.initialize_agenttrace() is False
    assert business_function() == "business-result"
    assert fake.agent_calls == 0
