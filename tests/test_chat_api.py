from fastapi.testclient import TestClient

import main
from main import app
from rag.service import RagConfigurationError


def test_assistant_page_keeps_selected_context():
    response = TestClient(app).get(
        "/assistant?level=CP&subject=Math%C3%A9matiques&topic=Fractions"
    )

    assert response.status_code == 200
    assert "assistant-question" in response.text
    assert "Fractions" in response.text
    assert "/static/assistant.js" in response.text


def test_chat_api_returns_sources_from_rag_service(monkeypatch):
    class FakeService:
        def answer(self, **kwargs):
            assert kwargs["level"] == "CP"
            assert kwargs["subject"] == "Mathématiques"
            return {
                "answer": "Réponse vérifiée [S1].",
                "sources": [{"id": "S1", "title": "Guide", "page": 4}],
                "evidence_status": "documented",
            }

    monkeypatch.setattr(main, "get_rag_service", lambda: FakeService())
    response = TestClient(app).post(
        "/api/chat",
        json={
            "level": "CP",
            "subject": "Mathématiques",
            "topic": "Fractions",
            "messages": [{"role": "user", "content": "Prépare une activité."}],
        },
    )

    assert response.status_code == 200
    assert response.json()["sources"][0]["page"] == 4
    assert response.json()["evidence_status"] == "documented"


def test_chat_api_reports_missing_configuration_without_leaking_details(monkeypatch):
    def raise_configuration_error():
        raise RagConfigurationError("Configuration incomplète: secret detail")

    monkeypatch.setattr(main, "get_rag_service", raise_configuration_error)
    response = TestClient(app).post(
        "/api/chat",
        json={
            "level": "CP",
            "subject": "Français",
            "messages": [{"role": "user", "content": "Prépare une activité."}],
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rag_not_configured"
    assert "secret detail" not in response.text


def test_chat_api_rejects_unsupported_level():
    response = TestClient(app).post(
        "/api/chat",
        json={
            "level": "6AP",
            "subject": "Français",
            "messages": [{"role": "user", "content": "Prépare une activité."}],
        },
    )

    assert response.status_code == 422