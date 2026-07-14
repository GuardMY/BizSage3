"""Application configuration loaded from environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """BizSage3 configuration, populated from .env file and environment."""

    # Database
    database_url: str = "sqlite+aiosqlite:///bizsage.db"
    checkpoint_db_url: str = "sqlite+aiosqlite:///checkpoints.db"

    # LLM
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-3.5-turbo"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048

    # Completeness threshold per design doc
    complete_threshold: int = 80

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
