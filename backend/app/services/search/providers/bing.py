"""Bing Web Search v7 HTTP adapter."""

from __future__ import annotations

from datetime import datetime

import httpx

from app.services.search.contracts import SearchResult, WebSearchRequest
from app.services.search.providers.base import WebSearchProviderError, WebSearchProviderUnavailable


class BingWebSearchProvider:
    name = "bing"

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str,
        timeout_seconds: float = 8.0,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds

    async def search(self, request: WebSearchRequest) -> list[SearchResult]:
        if not self._api_key:
            raise WebSearchProviderUnavailable("Bing Search API key is not configured")

        query = request.query
        if request.domains:
            query = f"({query}) " + " OR ".join(f"site:{domain}" for domain in request.domains)
        params: dict[str, str | int] = {"q": query, "count": request.limit, "textDecorations": False}
        bing_freshness = {"day": "Day", "week": "Week", "month": "Month"}
        if request.freshness in bing_freshness:
            params["freshness"] = bing_freshness[request.freshness]
        if request.language:
            params["mkt"] = request.language

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(
                    self._endpoint,
                    params=params,
                    headers={"Ocp-Apim-Subscription-Key": self._api_key},
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise WebSearchProviderError("Bing search request failed") from exc

        values = data.get("webPages", {}).get("value", []) if isinstance(data, dict) else []
        results: list[SearchResult] = []
        for rank, item in enumerate(values[: request.limit], start=1):
            if not isinstance(item, dict):
                continue
            results.append(SearchResult(
                citation_id="",
                title=str(item.get("name") or item.get("url") or "未命名网页资料"),
                url=_clean_url(item.get("url")),
                snippet=str(item.get("snippet") or "")[:4000],
                source_type="web",
                provider=self.name,
                published_at=_parse_datetime(item.get("dateLastCrawled")),
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
