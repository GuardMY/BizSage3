"""Test fixtures for backend tests."""

import pytest
from app.services.model_service import MockDiagnosisModel, create_model


@pytest.fixture
def mock_model():
    """Return a MockDiagnosisModel for deterministic testing."""
    return MockDiagnosisModel()


@pytest.fixture(autouse=True)
def use_mock_model(monkeypatch):
    """Force mock model for all tests by default."""
    monkeypatch.setattr("app.services.workflow.create_model", lambda: MockDiagnosisModel())
    monkeypatch.setattr("app.services.model_service.settings.llm_mode", "mock")
