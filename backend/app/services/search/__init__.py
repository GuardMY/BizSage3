"""Read-only search abstractions used by the conversation tool loop."""

from .contracts import SearchResult, SearchResponse, WebSearchRequest
from .router import SearchRouter, create_web_search_router

__all__ = [
    "SearchResult",
    "SearchResponse",
    "SearchRouter",
    "WebSearchRequest",
    "create_web_search_router",
]
