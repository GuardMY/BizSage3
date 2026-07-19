"""ASGI entry point for the dedicated AgentTrace Compose service."""

from agenttrace.config import load_config
from agenttrace.server.app import create_app


app = create_app(config=load_config())
