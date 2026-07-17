"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """BizSage3 configuration, populated from .env file and environment."""

    # Database
    database_url: str = "postgresql+asyncpg://bizsage_app:bizsage@localhost:5432/bizsage"
    checkpoint_db_url: str = "postgresql://bizsage_app:bizsage@localhost:5432/bizsage_checkpoint"
    checkpoint_setup_on_start: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_pool_timeout_seconds: float = 10.0
    db_pool_recycle_seconds: int = 1800
    db_application_name: str = "bizsage-api"
    db_statement_timeout_ms: int = 30000
    db_idle_transaction_timeout_ms: int = 60000
    checkpoint_pool_size: int = 5

    # Distributed coordination and background jobs.
    redis_url: str = "redis://localhost:6379/0"
    session_lock_ttl_seconds: int = 120
    report_queue_name: str = "arq:report"
    knowledge_queue_name: str = "arq:knowledge"
    report_worker_concurrency: int = 4
    knowledge_worker_concurrency: int = 2
    background_job_max_attempts: int = 3
    background_job_stale_seconds: int = 900

    # LLM
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-3.5-turbo"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048
    # Full LLM prompts, tool schemas/results, and model outputs are sensitive.
    llm_trace_enabled: bool = False

    # Knowledge base: OpenAI-compatible embeddings, object storage and vectors.
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "knowledge_chunks"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket: str = "bizsage-knowledge"
    knowledge_upload_max_bytes: int = 20 * 1024 * 1024
    industry_catalog_dir: str = str(
        Path(__file__).resolve().parents[2] / "docs" / "industry"
    )
    industry_catalog_sync_on_startup: bool = True

    # Public web search. Providers stay disabled until explicitly enabled and
    # configured, so a missing credential never blocks a conversation.
    web_search_enabled: bool = False
    web_search_strategy: str = "fallback"
    web_search_providers: str = "tavily,bing"
    web_search_timeout_seconds: float = 8.0
    web_search_total_timeout_seconds: float = 10.0
    web_search_max_results: int = 5
    web_search_max_query_length: int = 500
    web_search_max_domains: int = 5
    web_search_max_tool_calls: int = 4
    web_search_retries: int = 1
    tavily_api_key: str = ""
    bing_search_api_key: str = ""
    bing_search_endpoint: str = "https://api.bing.microsoft.com/v7.0/search"

    # Completeness threshold per design doc
    complete_threshold: int = 80

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Access control. ADMIN_TOKEN must be set before the protected API can be used.
    admin_token: str = ""
    auth_session_hours: int = 12
    auth_cookie_name: str = "bizsage_session"
    auth_cookie_secure: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()


def embedding_api_key() -> str:
    """Use a dedicated embedding credential only when one is configured."""
    return settings.embedding_api_key or settings.openai_api_key


def embedding_base_url() -> str:
    """Use a dedicated embedding endpoint only when one is configured."""
    return settings.embedding_base_url or settings.openai_base_url
