import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

MIN_GAP = timedelta(hours=12)
KEEP = timedelta(days=180)

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
  platform TEXT, listing_id TEXT, first_seen TEXT, score REAL, notified INTEGER,
  PRIMARY KEY (platform, listing_id));
CREATE TABLE IF NOT EXISTS runs (
  started_at TEXT, finished_ok INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS platform_ok (platform TEXT PRIMARY KEY, last_ok TEXT);
"""


def now() -> datetime:
    return datetime.now(UTC)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def is_seen(self, platform: str, listing_id: str) -> bool:
        q = "SELECT 1 FROM seen WHERE platform=? AND listing_id=?"
        return self.db.execute(q, (platform, listing_id)).fetchone() is not None

    def record(self, platform: str, listing_id: str, score: float, notified: bool) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO seen VALUES (?,?,?,?,?)",
            (platform, listing_id, now().isoformat(), score, int(notified)),
        )
        self.db.commit()

    def last_ok_run(self) -> datetime | None:
        row = self.db.execute("SELECT max(started_at) FROM runs WHERE finished_ok=1").fetchone()
        return datetime.fromisoformat(row[0]) if row[0] else None

    def too_soon(self) -> bool:
        last = self.last_ok_run()
        return last is not None and now() - last < MIN_GAP

    def record_run(self, started: datetime, ok: bool, status: str) -> None:
        self.db.execute("INSERT INTO runs VALUES (?,?,?)", (started.isoformat(), int(ok), status))
        self.db.execute("DELETE FROM seen WHERE first_seen < ?", ((now() - KEEP).isoformat(),))
        self.db.commit()

    def last_ok(self, platform: str) -> datetime | None:
        """Start of the last run in which this platform was searched without being blocked."""
        q = "SELECT last_ok FROM platform_ok WHERE platform=?"
        row = self.db.execute(q, (platform,)).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def mark_ok(self, platform: str, when: datetime) -> None:
        self.db.execute(
            "INSERT INTO platform_ok VALUES (?,?) ON CONFLICT(platform) DO UPDATE SET last_ok=?",
            (platform, when.isoformat(), when.isoformat()),
        )
        self.db.commit()

    def stopped_sent(self) -> bool:
        return self.db.execute("SELECT 1 FROM runs WHERE status='stopped'").fetchone() is not None
