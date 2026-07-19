"""Optional AgentTrace integration for the user conversation path."""

from __future__ import annotations

import functools
import inspect
import logging
import threading
from collections.abc import Callable
from typing import Any, TypeVar, cast

from app.config import settings

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

try:
    from agenttrace import trace as _trace
except Exception as exc:  # pragma: no cover - exercised when the optional wheel is absent
    _trace = None
    _import_error: Exception | None = exc
else:
    _import_error = None

_initialized = False
_initialization_lock = threading.Lock()


def initialize_agenttrace() -> bool:
    """Initialize AgentTrace once, degrading to no-op on every failure."""
    global _initialized

    if not settings.agenttrace_enabled:
        return False
    if _initialized:
        return True
    if _trace is None:
        logger.warning("AgentTrace is enabled but unavailable: %s", _import_error)
        return False

    with _initialization_lock:
        if _initialized:
            return True
        try:
            _trace.configure(
                project=settings.agenttrace_project,
                storage="sqlite",
                storage_url=settings.agenttrace_storage_url or None,
                capture_input=settings.agenttrace_capture_input,
                capture_output=settings.agenttrace_capture_output,
                strict_mode=False,
                auto_instrument=[],
                stdlib_logging=True,
                redaction={"enabled": True},
            )
        except Exception:
            logger.exception("AgentTrace initialization failed; conversation tracing is disabled")
            return False
        _initialized = True

    logger.info("AgentTrace conversation monitoring initialized")
    return True


def flush_agenttrace() -> None:
    """Flush pending trace data without affecting application shutdown."""
    if not _initialized or _trace is None:
        return
    try:
        _trace.flush(timeout=settings.agenttrace_flush_timeout_seconds)
    except Exception:
        logger.exception("AgentTrace flush failed during shutdown")


def _is_active() -> bool:
    return _initialized and _trace is not None


def _decorate(kind: str, **options: Any) -> Callable[[F], F]:
    """Create a runtime-gated AgentTrace decorator."""

    def decorator(function: F) -> F:
        if not settings.agenttrace_enabled or _trace is None:
            return function

        trace_options = {
            "capture_input": settings.agenttrace_capture_input,
            "capture_output": settings.agenttrace_capture_output,
            **options,
        }
        try:
            traced = getattr(_trace, kind)(**trace_options)(function)
        except Exception:
            logger.exception("Failed to instrument %s with AgentTrace", function.__qualname__)
            return function

        if inspect.isasyncgenfunction(function):
            @functools.wraps(function)
            async def async_generator_wrapper(*args: Any, **kwargs: Any):
                target = traced if _is_active() else function
                async for item in target(*args, **kwargs):
                    yield item

            return cast(F, async_generator_wrapper)

        if inspect.isgeneratorfunction(function):
            @functools.wraps(function)
            def generator_wrapper(*args: Any, **kwargs: Any):
                target = traced if _is_active() else function
                yield from target(*args, **kwargs)

            return cast(F, generator_wrapper)

        if inspect.iscoroutinefunction(function):
            @functools.wraps(function)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                target = traced if _is_active() else function
                return await target(*args, **kwargs)

            return cast(F, async_wrapper)

        @functools.wraps(function)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            target = traced if _is_active() else function
            return target(*args, **kwargs)

        return cast(F, sync_wrapper)

    return decorator


def trace_turn(**options: Any) -> Callable[[F], F]:
    return _decorate("turn", **options)


def trace_agent(**options: Any) -> Callable[[F], F]:
    return _decorate("agent", **options)


def trace_llm(**options: Any) -> Callable[[F], F]:
    return _decorate("llm", **options)


def trace_tool(**options: Any) -> Callable[[F], F]:
    return _decorate("tool", **options)


def trace_retriever(**options: Any) -> Callable[[F], F]:
    return _decorate("retriever", **options)


def trace_guardrail(**options: Any) -> Callable[[F], F]:
    return _decorate("guardrail", **options)
