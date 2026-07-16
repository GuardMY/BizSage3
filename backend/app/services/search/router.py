"""Provider routing, failure isolation, result fusion, and URL de-duplication."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config import settings
from app.services.search.contracts import ProviderAttempt, SearchResponse, SearchResult, WebSearchRequest
from app.services.search.providers import BingWebSearchProvider, TavilyWebSearchProvider, WebSearchProvider
from app.services.search.providers.base import WebSearchProviderError, WebSearchProviderUnavailable


@dataclass(frozen=True, slots=True)
class SearchPolicy:
    strategy: Literal["fallback", "parallel", "specialized"] = "fallback"
    timeout_seconds: float = 8.0
    max_results: int = 5
    retries: int = 1
    specialized_provider_order: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderHealth:
    consecutive_failures: int = 0
    last_error_type: str | None = None
    last_success_at: datetime | None = None


class SearchRouter:
    """Keep provider protocol details, health, and routing out of the LLM layer."""

    def __init__(self, providers: list[WebSearchProvider], policy: SearchPolicy) -> None:
        self._providers = {provider.name: provider for provider in providers}
        self._provider_order = [provider.name for provider in providers]
        self._policy = policy
        self._health = {name: ProviderHealth() for name in self._provider_order}

    async def search(self, request: WebSearchRequest) -> SearchResponse:
        providers = self._select_providers(request)
        if not providers:
            return SearchResponse(unavailable_reason="未配置可用的网页搜索供应商")
        if self._policy.strategy == "parallel":
            return await self._search_parallel(providers, request)
        return await self._search_fallback(providers, request)

    def _select_providers(self, request: WebSearchRequest) -> list[WebSearchProvider]:
        names = self._provider_order
        if self._policy.strategy == "specialized" and request.language:
            language = request.language.lower().split("-", maxsplit=1)[0]
            preferred = self._policy.specialized_provider_order.get(language, ())
            names = [*preferred, *(name for name in names if name not in preferred)]
        return [self._providers[name] for name in names if name in self._providers]

    async def _search_fallback(self, providers: list[WebSearchProvider], request: WebSearchRequest) -> SearchResponse:
        attempts: list[ProviderAttempt] = []
        for provider in providers:
            results, attempt = await self._attempt(provider, request)
            attempts.append(attempt)
            if results is not None:
                return SearchResponse(results=_rank_results(results, request.limit), attempts=attempts)
        return SearchResponse(attempts=attempts, unavailable_reason="所有网页搜索供应商当前不可用")

    async def _search_parallel(self, providers: list[WebSearchProvider], request: WebSearchRequest) -> SearchResponse:
        outcomes = await asyncio.gather(*(self._attempt(provider, request) for provider in providers))
        attempts = [attempt for _, attempt in outcomes]
        merged = _merge_results([results for results, _ in outcomes if results is not None], request.limit)
        reason = None if merged else "所有网页搜索供应商当前不可用"
        return SearchResponse(results=merged, attempts=attempts, unavailable_reason=reason)

    async def _attempt(
        self,
        provider: WebSearchProvider,
        request: WebSearchRequest,
    ) -> tuple[list[SearchResult] | None, ProviderAttempt]:
        started = time.perf_counter()
        error_type: str | None = None
        status: Literal["success", "unavailable", "error", "timeout"] = "error"
        try:
            result: list[SearchResult] | None = None
            for attempt in range(self._policy.retries + 1):
                try:
                    result = await asyncio.wait_for(
                        provider.search(request), timeout=self._policy.timeout_seconds
                    )
                    break
                except asyncio.TimeoutError:
                    error_type = "timeout"
                    status = "timeout"
                except WebSearchProviderUnavailable:
                    error_type = "unavailable"
                    status = "unavailable"
                    break
                except WebSearchProviderError:
                    error_type = "provider_error"
                    status = "error"
                if attempt < self._policy.retries:
                    await asyncio.sleep(0.1 * (attempt + 1))
            if result is not None:
                self._mark_success(provider.name)
                elapsed = int((time.perf_counter() - started) * 1000)
                return result, ProviderAttempt(provider.name, "success", elapsed, len(result))
        except Exception:
            error_type = "unexpected_error"
            status = "error"

        self._mark_failure(provider.name, error_type or "provider_error")
        elapsed = int((time.perf_counter() - started) * 1000)
        return None, ProviderAttempt(provider.name, status, elapsed, error_type=error_type)

    def _mark_success(self, provider: str) -> None:
        health = self._health[provider]
        health.consecutive_failures = 0
        health.last_error_type = None
        health.last_success_at = datetime.now(timezone.utc)

    def _mark_failure(self, provider: str, error_type: str) -> None:
        health = self._health[provider]
        health.consecutive_failures += 1
        health.last_error_type = error_type


def create_web_search_router() -> SearchRouter:
    configured = [name.strip().lower() for name in settings.web_search_providers.split(",") if name.strip()]
    providers: list[WebSearchProvider] = []
    for name in configured:
        if name == "tavily":
            providers.append(TavilyWebSearchProvider(
                settings.tavily_api_key,
                timeout_seconds=settings.web_search_timeout_seconds,
            ))
        elif name == "bing":
            providers.append(BingWebSearchProvider(
                settings.bing_search_api_key,
                endpoint=settings.bing_search_endpoint,
                timeout_seconds=settings.web_search_timeout_seconds,
            ))
    strategy = settings.web_search_strategy.lower()
    if strategy not in {"fallback", "parallel", "specialized"}:
        strategy = "fallback"
    return SearchRouter(
        providers,
        SearchPolicy(
            strategy=strategy,
            timeout_seconds=settings.web_search_timeout_seconds,
            max_results=settings.web_search_max_results,
            retries=max(settings.web_search_retries, 0),
        ),
    )


def normalize_url(value: str | None) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        tracking = {"gclid", "fbclid", "mc_cid", "mc_eid"}
        query = [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in tracking
        ]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(sorted(query)), ""))
    except ValueError:
        return value.strip()


def _rank_results(results: list[SearchResult], limit: int) -> list[SearchResult]:
    return [replace(result, rank=index) for index, result in enumerate(results[:limit], start=1)]


def _merge_results(provider_results: list[list[SearchResult]], limit: int) -> list[SearchResult]:
    candidates: dict[str, tuple[float, SearchResult]] = {}
    for results in provider_results:
        for result in results:
            key = normalize_url(result.url) or f"{result.title.casefold()}::{result.snippet[:120].casefold()}"
            score = 1.0 / (60 + max(result.rank, 1))
            previous = candidates.get(key)
            if previous is None:
                candidates[key] = (score, result)
                continue
            previous_score, previous_result = previous
            best = _prefer_result(previous_result, result)
            candidates[key] = (previous_score + score, best)
    ordered = sorted(candidates.values(), key=lambda value: value[0], reverse=True)
    return [replace(result, rank=index) for index, (_, result) in enumerate(ordered[:limit], start=1)]


def _prefer_result(left: SearchResult, right: SearchResult) -> SearchResult:
    if len(right.snippet) != len(left.snippet):
        return right if len(right.snippet) > len(left.snippet) else left
    if left.published_at != right.published_at:
        return right if right.published_at and (not left.published_at or right.published_at > left.published_at) else left
    return right if right.rank < left.rank else left
