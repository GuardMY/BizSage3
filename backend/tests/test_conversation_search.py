"""Focused coverage for the P1 tool loop and P2 citation boundary."""

from __future__ import annotations

import pytest
import httpx
from langchain_core.messages import AIMessage

from app.domain.schemas import ConversationCitation
from app.services.model_service import OpenAICompatibleModel, validate_conversation_citations
from app.services.search.contracts import SearchResult, WebSearchRequest
from app.services.search.providers.base import WebSearchProviderError
from app.services.search.providers.bing import BingWebSearchProvider
from app.services.search.providers.tavily import TavilyWebSearchProvider
from app.services.search.router import SearchPolicy, SearchRouter
from app.services.workflow import route_after_scene


class FakeProvider:
    def __init__(self, name: str, result: list[SearchResult] | Exception) -> None:
        self.name = name
        self.result = result
        self.calls = 0

    async def search(self, request: WebSearchRequest) -> list[SearchResult]:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeHttpClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.post_args = None
        self.get_args = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, *args, **kwargs):
        self.post_args = (args, kwargs)
        return self.response

    async def get(self, *args, **kwargs):
        self.get_args = (args, kwargs)
        return self.response


def web_result(*, url: str, snippet: str, rank: int = 1) -> SearchResult:
    return SearchResult(
        citation_id="",
        title="行业资料",
        url=url,
        snippet=snippet,
        source_type="web",
        provider="fake",
        rank=rank,
    )


@pytest.mark.asyncio
async def test_search_router_falls_back_after_provider_failure():
    primary = FakeProvider("primary", WebSearchProviderError("rate limited"))
    secondary = FakeProvider("secondary", [web_result(url="https://example.com/a", snippet="备用结果")])
    router = SearchRouter([primary, secondary], SearchPolicy(retries=0))

    response = await router.search(WebSearchRequest(query="餐饮客流"))

    assert [attempt.status for attempt in response.attempts] == ["error", "success"]
    assert response.results[0].url == "https://example.com/a"
    assert primary.calls == 1
    assert secondary.calls == 1


@pytest.mark.asyncio
async def test_parallel_search_normalizes_urls_and_deduplicates_results():
    first = FakeProvider("first", [web_result(
        url="https://example.com/market?utm_source=ad",
        snippet="较短摘要",
    )])
    second = FakeProvider("second", [web_result(
        url="https://example.com/market",
        snippet="这是来自第二个供应商、更完整的摘要内容",
    )])
    router = SearchRouter([first, second], SearchPolicy(strategy="parallel", retries=0))

    response = await router.search(WebSearchRequest(query="市场变化"))

    assert len(response.results) == 1
    assert response.results[0].snippet == "这是来自第二个供应商、更完整的摘要内容"
    assert response.results[0].rank == 1


@pytest.mark.asyncio
async def test_tavily_adapter_normalizes_provider_response(monkeypatch):
    client = FakeHttpClient(httpx.Response(
        200,
        json={"results": [{
            "title": "Tavily 资料",
            "url": "https://example.com/tavily",
            "content": "网页摘要",
            "published_date": "2026-07-16T10:00:00Z",
        }]},
        request=httpx.Request("POST", "https://api.tavily.com/search"),
    ))
    monkeypatch.setattr("app.services.search.providers.tavily.httpx.AsyncClient", lambda **_: client)

    results = await TavilyWebSearchProvider("key").search(WebSearchRequest(query="政策", limit=1))

    assert results[0].title == "Tavily 资料"
    assert results[0].source_type == "web"
    assert results[0].published_at is not None
    assert client.post_args[1]["json"]["max_results"] == 1


@pytest.mark.asyncio
async def test_bing_adapter_maps_response_and_omits_unsupported_year_filter(monkeypatch):
    client = FakeHttpClient(httpx.Response(
        200,
        json={"webPages": {"value": [{
            "name": "Bing 资料",
            "url": "https://example.com/bing",
            "snippet": "网页摘要",
            "dateLastCrawled": "2026-07-16T10:00:00Z",
        }]}},
        request=httpx.Request("GET", "https://bing.example/search"),
    ))
    monkeypatch.setattr("app.services.search.providers.bing.httpx.AsyncClient", lambda **_: client)

    results = await BingWebSearchProvider("key", endpoint="https://bing.example/search").search(
        WebSearchRequest(query="政策", freshness="year", limit=1)
    )

    assert results[0].title == "Bing 资料"
    assert results[0].provider == "bing"
    assert "freshness" not in client.get_args[1]["params"]


def test_conversation_citation_validation_removes_fabricated_numbers():
    candidates = [
        ConversationCitation(
            citation_id="1",
            source_type="knowledge",
            title="已审核资料",
            quote="资料正文",
        ),
    ]

    reply, selected = validate_conversation_citations(
        "可信结论。[资料 1] 虚构结论。[资料 9]",
        candidates,
    )

    assert reply == "可信结论。[资料 1] 虚构结论。"
    assert selected == candidates


class StubToolExecutor:
    def __init__(self) -> None:
        self.evidence = [ConversationCitation(
            citation_id="1",
            source_type="web",
            title="政策网页",
            url="https://example.com/policy",
            quote="政策摘要",
            provider="fake",
        )]
        self.invocations = []
        self.calls: list[tuple[str, object]] = []

    async def execute(self, tool_name: str, args: object, scene: dict[str, str]) -> str:
        self.calls.append((tool_name, args))
        return '{"status":"success","results":[{"citation_id":"1"}]}'


class FakeToolLLM:
    def __init__(self) -> None:
        self.calls = 0

    def bind_tools(self, schemas):
        self.schemas = schemas
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[{
                "name": "search_web",
                "args": {"query": "最新政策"},
                "id": "call-1",
            }])
        return AIMessage(content=(
            '{"new_facts": [], "completeness": {"score": 10}, '
            '"reply": "政策有更新。[资料 1] 以及虚构来源。[资料 8]", '
            '"suggested_replies": []}'
        ))


@pytest.mark.asyncio
async def test_model_tool_loop_keeps_only_citations_returned_by_tools():
    executor = StubToolExecutor()
    model = OpenAICompatibleModel.__new__(OpenAICompatibleModel)
    model.llm = FakeToolLLM()
    model._tool_executor_factory = lambda: executor

    result = await model.conversation_turn(
        [{"role": "user", "content": "最近有什么新政策？"}],
        [],
        {"industry": "餐饮"},
    )

    assert executor.calls == [("search_web", {"query": "最新政策"})]
    assert result.reply == "政策有更新。[资料 1] 以及虚构来源。"
    assert result.citations == executor.evidence
    assert result.tool_evidence == executor.evidence


def test_scene_routing_enters_tool_enabled_conversation_turn_directly():
    assert route_after_scene({"user_scene": {"industry": "电商"}}) == "conversation_turn"
