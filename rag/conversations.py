import json
import logging
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))
logger = logging.getLogger(__name__)
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_TTL_SECONDS = 30 * 24 * 60 * 60


class ConversationStoreConfigurationError(Exception):
    """Raised when the Redis REST credentials or retention are invalid."""


class ConversationStoreError(Exception):
    """Raised when Redis cannot read or persist a conversation."""


class ConversationStore:
    def __init__(self, redis_client: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        if not 60 <= ttl_seconds <= MAX_TTL_SECONDS:
            raise ConversationStoreConfigurationError(
                "CONVERSATION_TTL_SECONDS doit être compris entre 60 et 2592000."
            )
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds

    @classmethod
    def from_environment(cls) -> "ConversationStore":
        url = os.getenv("UPSTASH_REDIS_REST_URL", "").strip()
        token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
        if not url or not token:
            raise ConversationStoreConfigurationError(
                "UPSTASH_REDIS_REST_URL et UPSTASH_REDIS_REST_TOKEN sont requis."
            )
        try:
            ttl_seconds = int(os.getenv("CONVERSATION_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))
            from upstash_redis import Redis

            return cls(Redis(url=url, token=token), ttl_seconds=ttl_seconds)
        except ConversationStoreConfigurationError:
            raise
        except Exception as error:
            logger.exception("Conversation Redis initialization failed")
            raise ConversationStoreConfigurationError(
                "La configuration Upstash Redis est invalide."
            ) from error

    @staticmethod
    def key(conversation_id: UUID | str) -> str:
        return f"classe-claire:conversation:{conversation_id}"

    def create(self, context: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        record = {
            "id": str(uuid4()),
            **context,
            "messages": [],
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=self.ttl_seconds)).isoformat(),
        }
        self.save(record)
        return record

    def get(self, conversation_id: UUID | str) -> dict[str, Any] | None:
        key = self.key(conversation_id)
        try:
            stored = self.redis.get(key)
            if stored is None:
                return None
            if isinstance(stored, bytes):
                stored = stored.decode("utf-8")
            record = json.loads(stored) if isinstance(stored, str) else stored
            self.redis.expire(key, self.ttl_seconds)
            record["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
            ).isoformat()
            return record
        except Exception as error:
            logger.exception("Conversation read failed")
            raise ConversationStoreError("La conversation n’a pas pu être chargée.") from error

    def save(self, record: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        record["updated_at"] = now.isoformat()
        record["expires_at"] = (now + timedelta(seconds=self.ttl_seconds)).isoformat()
        record["messages"] = record.get("messages", [])[-60:]
        try:
            self.redis.set(
                self.key(record["id"]),
                json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                ex=self.ttl_seconds,
            )
        except Exception as error:
            logger.exception("Conversation write failed")
            raise ConversationStoreError("La conversation n’a pas pu être sauvegardée.") from error

    def delete(self, conversation_id: UUID | str) -> None:
        try:
            self.redis.delete(self.key(conversation_id))
        except Exception as error:
            logger.exception("Conversation deletion failed")
            raise ConversationStoreError("La conversation n’a pas pu être supprimée.") from error


@lru_cache(maxsize=1)
def get_conversation_store() -> ConversationStore:
    return ConversationStore.from_environment()