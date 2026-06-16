from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionItem:
    value: Any
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class TemporarySessionStore:
    """In-memory temporary store keyed by browser session id."""

    def __init__(self, ttl_seconds: int = 60 * 60) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, SessionItem] = {}
        self._lock = threading.Lock()

    def set(self, session_id: str, value: Any) -> None:
        self.cleanup()

        now = time.time()
        with self._lock:
            self._items[session_id] = SessionItem(
                value=value,
                created_at=now,
                updated_at=now,
            )

    def get(self, session_id: str) -> Any | None:
        self.cleanup()

        with self._lock:
            item = self._items.get(session_id)

            if item is None:
                return None

            item.updated_at = time.time()
            return item.value

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._items.pop(session_id, None)

    def cleanup(self) -> None:
        now = time.time()

        with self._lock:
            expired_keys = [
                key
                for key, item in self._items.items()
                if now - item.updated_at > self.ttl_seconds
            ]

            for key in expired_keys:
                self._items.pop(key, None)