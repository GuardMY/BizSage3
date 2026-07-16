"""Provider-neutral contracts for public web search."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class WebSearchRequest:
    query: str
    freshness: str | None = None
    domains: list[str] = field(default_factory=list)
    language: str | None = None
    limit: int = 5


@dataclass(frozen=True, slots=True)
class SearchResult:
    citation_id: str
    title: str
    url: str | None
    snippet: str
    source_type: Literal["knowledge", "web"]
    provider: str | None
    locator: dict[str, Any] = field(default_factory=dict)
    published_at: datetime | None = None
    rank: int = 0


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    provider: str
    status: Literal["success", "unavailable", "error", "timeout"]
    latency_ms: int
    result_count: int = 0
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResponse:
    results: list[SearchResult] = field(default_factory=list)
    attempts: list[ProviderAttempt] = field(default_factory=list)
    unavailable_reason: str | None = None
