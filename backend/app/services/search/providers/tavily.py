"""Tavily HTTP adapter with no dependency leaking into the router."""

from __future__ import annotations

from datetime import datetime

import httpx

from app.services.search.contracts import SearchResult, WebSearchRequest
from app.services.search.providers.base import WebSearchProviderError, WebSearchProviderUnavailable


class TavilyWebSearchProvider:
    name = "tavily"

    def __init__(self, api_key: str, *, timeout_seconds: float = 8.0) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    async def search(self, request: WebSearchRequest) -> list[SearchResult]:
        if not self._api_key:
            raise WebSearchProviderUnavailable("Tavily API key is not configured")

        payload: dict[str, object] = {
            "api_key": self._api_key,
            "query": request.query,
            "max_results": request.limit,
            "search_depth": "basic",
        }
        if request.freshness:
            payload["time_range"] = request.freshness
        if request.domains:
            payload["include_domains"] = request.domains

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post("https://api.tavily.com/search", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise WebSearchProviderError("Tavily request failed") from exc

        results: list[SearchResult] = []
        for rank, item in enumerate(data.get("results", [])[: request.limit], start=1):
            if not isinstance(item, dict):
                continue
            results.append(SearchResult(
                citation_id="",
                title=str(item.get("title") or item.get("url") or "未命名网页资料"),
                url=_clean_url(item.get("url")),
                snippet=str(item.get("content") or "")[:4000],
                source_type="web",
                provider=self.name,
                published_at=_parse_datetime(item.get("published_date")),
                rank=rank,
            ))
        return results


def _clean_url(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
