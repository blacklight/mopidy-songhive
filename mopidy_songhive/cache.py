"""
Persistent metadata cache.

Two-level store for Songhive entity payloads (tracks, podcast episodes,
remote objects): an in-memory dict in front of a SQLite database kept in
the extension's cache directory, so fetched metadata survives restarts
and large libraries do not have to be re-fetched on every Mopidy
startup.

Entries never expire on their own. Freshness is the callers' job: every
collection listing re-seeds the entries it returns, and playback always
re-fetches a track's payload before streaming it (the ``fresh``
parameter on ``SonghiveClient.get_track`` and friends), so stale data
can at most show up in browse/lookup results until then.
"""

import contextlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    kind TEXT NOT NULL,
    item_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    PRIMARY KEY (kind, item_id)
)
"""


class MetadataCache:
    """Memory + on-disk cache for Songhive API payloads.

    ``cache_dir`` is the extension's cache directory (see
    ``Extension.get_cache_dir``); when ``None`` — or when the database
    cannot be opened — the cache degrades to in-memory only.
    """

    def __init__(self, cache_dir=None):
        self._memory = {}
        self._lock = threading.Lock()
        self._db = None
        if cache_dir is None:
            return
        try:
            path = Path(cache_dir) / "metadata.db"
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._db.execute(_SCHEMA)
            self._db.commit()
        except (OSError, sqlite3.Error) as exc:
            logger.info("Songhive metadata cache disabled: %s", exc)
            if self._db is not None:
                with contextlib.suppress(sqlite3.Error):
                    self._db.close()
                self._db = None

    def get(self, kind, item_id):
        """Return the cached payload for ``(kind, item_id)``, or None."""
        key = (kind, str(item_id))
        with contextlib.suppress(KeyError):
            return self._memory[key]
        if self._db is None:
            return None
        try:
            with self._lock:
                row = self._db.execute(
                    "SELECT payload FROM metadata"
                    " WHERE kind = ? AND item_id = ?",
                    key,
                ).fetchone()
        except sqlite3.Error as exc:
            logger.debug("Songhive cache read failed: %s", exc)
            return None
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
        except ValueError:
            return None
        self._memory[key] = payload
        return payload

    def set(self, kind, item_id, payload):
        """Cache one payload under ``(kind, item_id)``."""
        key = (kind, str(item_id))
        self._memory[key] = payload
        if self._db is None:
            return
        try:
            blob = json.dumps(payload)
        except (TypeError, ValueError):
            return
        try:
            with self._lock:
                self._db.execute(
                    "INSERT OR REPLACE INTO metadata"
                    " (kind, item_id, payload, fetched_at)"
                    " VALUES (?, ?, ?, ?)",
                    (kind, str(item_id), blob, time.time()),
                )
                self._db.commit()
        except sqlite3.Error as exc:
            logger.debug("Songhive cache write failed: %s", exc)

    def set_many(self, kind, payloads):
        """Cache an iterable of payload dicts, keyed on their ``id``."""
        rows = []
        now = time.time()
        for payload in payloads:
            if not isinstance(payload, dict) or payload.get("id") is None:
                continue
            item_id = str(payload["id"])
            self._memory[(kind, item_id)] = payload
            try:
                rows.append((kind, item_id, json.dumps(payload), now))
            except (TypeError, ValueError):
                continue
        if not rows or self._db is None:
            return
        try:
            with self._lock:
                self._db.executemany(
                    "INSERT OR REPLACE INTO metadata"
                    " (kind, item_id, payload, fetched_at)"
                    " VALUES (?, ?, ?, ?)",
                    rows,
                )
                self._db.commit()
        except sqlite3.Error as exc:
            logger.debug("Songhive cache write failed: %s", exc)

    def invalidate(self, kind, item_id):
        """Drop the ``(kind, item_id)`` entry, e.g. after a 404."""
        key = (kind, str(item_id))
        self._memory.pop(key, None)
        if self._db is None:
            return
        try:
            with self._lock:
                self._db.execute(
                    "DELETE FROM metadata WHERE kind = ? AND item_id = ?",
                    key,
                )
                self._db.commit()
        except sqlite3.Error as exc:
            logger.debug("Songhive cache delete failed: %s", exc)
