"""Provider boundary. Router and tools only depend on this protocol."""

from __future__ import annotations

from typing import Protocol

from app.services.search.contracts import SearchResult, WebSearchRequest


class WebSearchProvider(Protocol):
    name: str

    async def search(self, request: WebSearchRequest) -> list[SearchResult]:
        ...


class WebSearchProviderError(RuntimeError):
    """A provider request was attempted but did not complete successfully."""


class WebSearchProviderUnavailable(WebSearchProviderError):
    """A provider is disabled or has no usable credential."""
