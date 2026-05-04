import sqlite3
from pathlib import Path
from typing import Any


class SQLiteTelemetryStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rate_limit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    route_path TEXT NOT NULL,
                    identifier TEXT NOT NULL,
                    allowed INTEGER NOT NULL,
                    remaining INTEGER NOT NULL,
                    capacity INTEGER NOT NULL,
                    rate REAL NOT NULL,
                    retry_after_s INTEGER,
                    redis_fail_open INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rate_limit_events_timestamp
                ON rate_limit_events(timestamp)
                """
            )

    def record(self, event: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rate_limit_events (
                    timestamp,
                    route_path,
                    identifier,
                    allowed,
                    remaining,
                    capacity,
                    rate,
                    retry_after_s,
                    redis_fail_open
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.timestamp,
                    event.route_path,
                    event.identifier,
                    int(event.allowed),
                    event.remaining,
                    event.capacity,
                    event.rate,
                    event.retry_after_s,
                    int(event.redis_fail_open),
                ),
            )

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    id,
                    timestamp,
                    route_path,
                    identifier,
                    allowed,
                    remaining,
                    capacity,
                    rate,
                    retry_after_s,
                    redis_fail_open
                FROM rate_limit_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            {
                **dict(row),
                "allowed": bool(row["allowed"]),
                "redis_fail_open": bool(row["redis_fail_open"]),
            }
            for row in rows
        ]

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS events,
                    SUM(CASE WHEN allowed = 0 THEN 1 ELSE 0 END) AS denied,
                    SUM(CASE WHEN redis_fail_open = 1 THEN 1 ELSE 0 END) AS redis_fail_open
                FROM rate_limit_events
                """
            ).fetchone()

        return {
            "path": str(self.path),
            "events": int(row["events"] or 0),
            "denied": int(row["denied"] or 0),
            "redis_fail_open": int(row["redis_fail_open"] or 0),
        }
