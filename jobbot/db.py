from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Job, Verdict, short_id

# Status values:
#   dropped       failed a hard filter (reason says why)
#   old           passed, but posted too long ago to be worth an alert
#   low_score     passed, score under alert_min_score
#   duplicate     same company + title already alerted from another source
#   muted         a match found while alerts were paused (/pause); shown in /today
#   alerted       sent to you
#   alert_failed  send failed, retried next cycle
#   applied / skipped   set by you with the Telegram buttons
MATCH_STATUSES = ("alerted", "applied", "skipped", "muted")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key           TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    company       TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    location      TEXT,
    fingerprint   TEXT,
    posted_at     TEXT,
    first_seen_at TEXT NOT NULL,
    status        TEXT NOT NULL,
    score         REAL,
    reason        TEXT,
    alerted_at    TEXT,
    message_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Columns added after the first release. Added on startup if missing.
MIGRATIONS = {
    "cb_id": "ALTER TABLE jobs ADD COLUMN cb_id TEXT",          # short id for Telegram buttons
    "status_at": "ALTER TABLE jobs ADD COLUMN status_at TEXT",  # when status last changed
    "ai_score": "ALTER TABLE jobs ADD COLUMN ai_score REAL",    # AI score, when the AI check ran
    "ai_json": "ALTER TABLE jobs ADD COLUMN ai_json TEXT",      # raw AI answer
    "description": "ALTER TABLE jobs ADD COLUMN description TEXT",  # job text, kept for matches (CV tailoring)
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, path: str | Path, read_only: bool = False):
        """read_only (dry runs): open an existing database without writing, or use an empty
        in-memory one when there is none yet. Nothing is created on disk."""
        # Source threads and the Telegram thread read and write. One lock keeps it simple.
        self.lock = threading.RLock()
        self.read_only = read_only
        if read_only and Path(path).exists():
            uri = Path(path).resolve().as_uri() + "?mode=ro"
            self.conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            return
        if read_only:
            path = ":memory:"
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(jobs)")}
        for col, sql in MIGRATIONS.items():
            if col not in cols:
                self.conn.execute(sql)
        self.conn.create_function("short_id", 1, short_id)
        self.conn.execute("UPDATE jobs SET cb_id = short_id(key) WHERE cb_id IS NULL")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_cb_id ON jobs(cb_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_alerted_at ON jobs(alerted_at)")
        self.conn.commit()

    # ---- jobs ------------------------------------------------------------------

    def status(self, key: str) -> str | None:
        with self.lock:
            row = self.conn.execute("SELECT status FROM jobs WHERE key = ?", (key,)).fetchone()
        return row["status"] if row else None

    def already_alerted(self, job: Job, days: int = 30) -> bool:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self.lock:
            row = self.conn.execute(
                "SELECT 1 FROM jobs WHERE fingerprint = ? AND key != ? AND alerted_at >= ? LIMIT 1",
                (job.fingerprint, job.key, since),
            ).fetchone()
        return row is not None

    def record(self, job: Job, status: str, verdict: Verdict | None = None, message_id: str | None = None) -> None:
        # "muted" counts as a match for /today, so it gets a match time too.
        match = status in ("alerted", "muted")
        alerted_at = _now() if match else None
        description = job.description if match else None  # only for matches, keeps the DB small
        ai = getattr(verdict, "ai", None)
        with self.lock:
            self.conn.execute(
                """
                INSERT INTO jobs (key, source, company, external_id, title, url, location, fingerprint,
                                  posted_at, first_seen_at, status, score, reason, alerted_at, message_id,
                                  cb_id, status_at, ai_score, ai_json, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    status = excluded.status,
                    score = excluded.score,
                    reason = excluded.reason,
                    alerted_at = COALESCE(excluded.alerted_at, jobs.alerted_at),
                    message_id = COALESCE(excluded.message_id, jobs.message_id),
                    status_at = excluded.status_at,
                    ai_score = COALESCE(excluded.ai_score, jobs.ai_score),
                    ai_json = COALESCE(excluded.ai_json, jobs.ai_json),
                    description = COALESCE(excluded.description, jobs.description)
                """,
                (
                    job.key, job.source, job.company, job.external_id, job.title, job.url, job.location,
                    job.fingerprint, job.posted_at.isoformat() if job.posted_at else None, _now(), status,
                    verdict.score if verdict else None, verdict.reason if verdict else None, alerted_at,
                    message_id, short_id(job.key), _now(),
                    ai.score if ai else None, ai.raw if ai else None, description,
                ),
            )
            self.conn.commit()

    def by_cb_id(self, cb_id: str) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute("SELECT * FROM jobs WHERE cb_id = ?", (cb_id,)).fetchone()

    def set_status(self, key: str, status: str) -> None:
        with self.lock:
            self.conn.execute("UPDATE jobs SET status = ?, status_at = ? WHERE key = ?", (status, _now(), key))
            self.conn.commit()

    def matches_since(self, since: datetime) -> list[sqlite3.Row]:
        """Jobs that matched (alerted, muted, then maybe applied/skipped) since a time, newest first."""
        marks = ",".join("?" * len(MATCH_STATUSES))
        with self.lock:
            return self.conn.execute(
                f"SELECT * FROM jobs WHERE alerted_at >= ? AND status IN ({marks}) ORDER BY alerted_at DESC",
                (since.astimezone(timezone.utc).isoformat(), *MATCH_STATUSES),
            ).fetchall()

    def counts(self) -> dict[str, int]:
        with self.lock:
            rows = self.conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    def match_counts_since(self, since: datetime) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.matches_since(since):
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return counts

    # ---- settings (pause flag) --------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str | None) -> None:
        with self.lock:
            if value is None:
                self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                self.conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
            self.conn.commit()

    def add_to_setting(self, key: str, amount: float) -> float:
        """Add to a numeric setting (daily and monthly counters) and return the new total."""
        with self.lock:
            value = float(self.get_setting(key, "0") or 0) + amount
            self.set_setting(key, repr(value))
        return value

    @property
    def paused(self) -> bool:
        return self.get_setting("paused_at") is not None
