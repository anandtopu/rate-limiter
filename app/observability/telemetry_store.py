import sqlite3
from pathlib import Path
from typing import Any

TELEMETRY_SCHEMA_COLUMNS = {
    "algorithm": "TEXT",
    "fail_mode": "TEXT",
    "tier": "TEXT",
    "owner": "TEXT",
    "sensitivity": "TEXT",
    "rule_version": "INTEGER",
    "method": "TEXT",
    "status_code": "INTEGER",
    "latency_ms": "REAL",
}


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
                    redis_fail_open INTEGER NOT NULL,
                    algorithm TEXT,
                    fail_mode TEXT,
                    tier TEXT,
                    owner TEXT,
                    sensitivity TEXT,
                    rule_version INTEGER,
                    method TEXT,
                    status_code INTEGER,
                    latency_ms REAL
                )
                """
            )
            self._migrate_schema(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rate_limit_events_timestamp
                ON rate_limit_events(timestamp)
                """
            )

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(rate_limit_events)").fetchall()
        }
        for column, column_type in TELEMETRY_SCHEMA_COLUMNS.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE rate_limit_events ADD COLUMN {column} {column_type}")

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
                    redis_fail_open,
                    algorithm,
                    fail_mode,
                    tier,
                    owner,
                    sensitivity,
                    rule_version,
                    method,
                    status_code,
                    latency_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    getattr(event, "algorithm", None),
                    getattr(event, "fail_mode", None),
                    getattr(event, "tier", None),
                    getattr(event, "owner", None),
                    getattr(event, "sensitivity", None),
                    getattr(event, "rule_version", None),
                    getattr(event, "method", None),
                    getattr(event, "status_code", None),
                    getattr(event, "latency_ms", None),
                ),
            )

    def _time_filter(
        self,
        since: float | None = None,
        until: float | None = None,
    ) -> tuple[str, list[float]]:
        clauses = []
        params: list[float] = []

        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)

        if not clauses:
            return "", params

        return f"WHERE {' AND '.join(clauses)}", params

    def recent(
        self,
        limit: int = 100,
        since: float | None = None,
        until: float | None = None,
    ) -> list[dict[str, Any]]:
        where_sql, params = self._time_filter(since=since, until=until)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
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
                    redis_fail_open,
                    algorithm,
                    fail_mode,
                    tier,
                    owner,
                    sensitivity,
                    rule_version,
                    method,
                    status_code,
                    latency_ms
                FROM rate_limit_events
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()

        return [
            {
                **dict(row),
                "allowed": bool(row["allowed"]),
                "redis_fail_open": bool(row["redis_fail_open"]),
            }
            for row in rows
        ]

    def summary(
        self,
        since: float | None = None,
        until: float | None = None,
    ) -> dict[str, Any]:
        where_sql, params = self._time_filter(since=since, until=until)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS events,
                    SUM(CASE WHEN allowed = 0 THEN 1 ELSE 0 END) AS denied,
                    SUM(CASE WHEN redis_fail_open = 1 THEN 1 ELSE 0 END) AS redis_fail_open
                FROM rate_limit_events
                {where_sql}
                """,
                params,
            ).fetchone()

        return {
            "path": str(self.path),
            "events": int(row["events"] or 0),
            "denied": int(row["denied"] or 0),
            "redis_fail_open": int(row["redis_fail_open"] or 0),
        }

    def analytics(
        self,
        limit: int = 5,
        since: float | None = None,
        until: float | None = None,
    ) -> dict[str, Any]:
        where_sql, params = self._time_filter(since=since, until=until)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            routes = conn.execute(
                f"""
                SELECT
                    route_path,
                    COUNT(*) AS requests,
                    SUM(CASE WHEN allowed = 0 THEN 1 ELSE 0 END) AS denied,
                    SUM(CASE WHEN redis_fail_open = 1 THEN 1 ELSE 0 END) AS redis_fail_open
                FROM rate_limit_events
                {where_sql}
                GROUP BY route_path
                ORDER BY requests DESC, route_path ASC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            offenders = conn.execute(
                f"""
                SELECT
                    identifier,
                    COUNT(*) AS denied
                FROM rate_limit_events
                WHERE allowed = 0
                {"AND " + where_sql.removeprefix("WHERE ") if where_sql else ""}
                GROUP BY identifier
                ORDER BY denied DESC, identifier ASC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()

        return {
            "routes": [self._route_row(row) for row in routes],
            "top_offenders": [dict(row) for row in offenders],
        }

    def _route_row(self, row: sqlite3.Row) -> dict[str, Any]:
        requests = int(row["requests"] or 0)
        denied = int(row["denied"] or 0)
        return {
            "route": row["route_path"],
            "requests": requests,
            "denied": denied,
            "denied_pct": round((denied / requests) * 100, 2) if requests else 0.0,
            "redis_fail_open": int(row["redis_fail_open"] or 0),
        }
