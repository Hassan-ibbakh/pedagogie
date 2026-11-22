import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from main import app
from rag.conversations import (
    ConversationStore,
    ConversationStoreConfigurationError,
)


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def set(self, key, value, ex):
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def get(self, key):
        return self.values.get(key)

    def expire(self, key, seconds):
        self.ttls[key] = seconds
        return True

    def delete(self, key):
        self.ttls.pop(key, None)
        return int(self.values.pop(key, None) is not None)


class FakeConversationStore:
    def __init__(self):
        self.records = {}

    def create(self, context):
        now = datetime.now(timezone.utc)
        record = {
            "id": str(uuid4()),
            **context,
            "messages": [],
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "expires_at": (now + timedelta(days=7)).isoformat(),
        }
        self.records[record["id"]] = record
        return record

    def get(self, conversation_id):
        return self.records.get(str(conversation_id))

    def save(self, record):
        self.records[record["id"]] = record

    def delete(self, conversation_id):
        self.records.pop(str(conversation_id), None)


def test_conversation_store_sets_and_refreshes_ttl():
    redis = FakeRedis()
    store = ConversationStore(redis, ttl_seconds=3600)
    record = store.create({"level": "CP", "subject": "Arabe", "messages": []})
    key = store.key(record["id"])

    assert redis.ttls[key] == 3600
    assert json.loads(redis.values[key])["level"] == "CP"
    assert store.get(record["id"])["subject"] == "Arabe"
    assert redis.ttls[key] == 3600

    record["messages"].append({"role": "user", "content": "Bonjour"})
    store.save(record)
    assert json.loads(redis.values[key])["messages"][0]["content"] == "Bonjour"
    store.delete(record["id"])
    assert store.get(record["id"]) is None


def test_conversation_ttl_is_bounded():
    with pytest.raises(ConversationStoreConfigurationError):
        ConversationStore(FakeRedis(), ttl_seconds=31 * 24 * 60 * 60)


def test_create_and_reload_conversation_api(monkeypatch):
    store = FakeConversationStore()
    monkeypatch.setattr(main, "get_conversation_store", lambda: store)
    client = TestClient(app)
    created = client.post(
        "/api/conversations",
        json={
            "level": "CE1",
            "subject": "Arabe",
            "topic": "Les nombres",
            "pedagogical_prompt": "Prépare une activité courte.",
        },
    )

    assert created.status_code == 200
    record = created.json()
    assert record["level"] == "CE1"
    restored = client.get(f"/api/conversations/{record['id']}")
    assert restored.status_code == 200
    assert restored.json()["pedagogical_prompt"] == "Prépare une activité courte."


def test_chat_saves_user_turn_answer_sources_and_expiry(monkeypatch):
    store = FakeConversationStore()
    record = store.create(
        {
            "level": "CP",
            "subject": "Mathématiques",
            "topic": "Nombres",
            "pedagogical_prompt": "Prépare une activité.",
            "resource_session": None,
        }
    )
    monkeypatch.setattr(main, "get_conversation_store", lambda: store)

    class FakeRag:
        def answer(self, **kwargs):
            assert kwargs["level"] == "CP"
            assert kwargs["pedagogical_prompt"] == "Prépare une activité."
            assert kwargs["messages"][-1]["content"] == "Compte jusqu’à cinq."
            return {
                "answer": "Réponse [S1].",
                "sources": [{"id": "S1", "title": "Guide", "page": 2}],
                "evidence_status": "documented",
            }

    monkeypatch.setattr(main, "get_rag_service", lambda: FakeRag())
    response = TestClient(app).post(
        "/api/chat",
        json={"conversation_id": record["id"], "message": "Compte jusqu’à cinq."},
    )

    assert response.status_code == 200
    assert response.json()["conversation_id"] == record["id"]
    assert response.json()["expires_at"]
    saved_messages = store.get(record["id"])["messages"]
    assert [message["role"] for message in saved_messages] == ["user", "assistant"]
    assert saved_messages[-1]["sources"][0]["page"] == 2


def test_expired_conversation_is_reported_and_can_be_deleted(monkeypatch):
    store = FakeConversationStore()
    monkeypatch.setattr(main, "get_conversation_store", lambda: store)
    client = TestClient(app)
    conversation_id = uuid4()

    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404
    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 200


def test_create_conversation_reports_missing_upstash_credentials(monkeypatch):
    def raise_missing_configuration():
        raise ConversationStoreConfigurationError("missing Upstash credentials")

    monkeypatch.setattr(main, "get_conversation_store", raise_missing_configuration)
    response = TestClient(app).post(
        "/api/conversations",
        json={"level": "CP", "subject": "Arabe"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "redis_not_configured"
    assert "missing Upstash credentials" not in response.text