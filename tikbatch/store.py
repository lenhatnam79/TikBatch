from __future__ import annotations

import csv
import json
import sqlite3
import time
from pathlib import Path

from .model import Video


class Store:
    """Owned by the engine event loop; no cross-thread SQLite access."""
    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(folder / ".tikbatch.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS videos (
              id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT, timestamp INTEGER,
              seed TEXT, state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER DEFAULT 0,
              ready REAL DEFAULT 0, error TEXT DEFAULT '', filename TEXT DEFAULT '',
              bytes INTEGER DEFAULT 0, sha256 TEXT DEFAULT '', width INTEGER DEFAULT 0,
              height INTEGER DEFAULT 0, provenance TEXT DEFAULT '');
            CREATE INDEX IF NOT EXISTS queue ON videos(state,ready);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        """)
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(videos)")}
        if "error_code" not in columns:
            self.db.execute("ALTER TABLE videos ADD COLUMN error_code TEXT NOT NULL DEFAULT ''")
        self.db.execute("UPDATE videos SET state='pending' WHERE state='active'")
        self.db.commit()

    def get(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str):
        self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
        self.db.commit()

    def add(self, v: Video):
        if not v.id.isdigit():
            return
        old = self.db.execute("SELECT seed FROM videos WHERE id=?", (v.id,)).fetchone()
        seed = v.seed
        # DOM links and flat listings must not erase richer API metadata.
        if old and not seed.get("item"):
            seed = json.loads(old["seed"] or "{}")
        self.db.execute("""INSERT INTO videos(id,url,title,timestamp,seed) VALUES (?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET seed=excluded.seed,
            title=CASE WHEN excluded.title!='' THEN excluded.title ELSE videos.title END,
            timestamp=CASE WHEN excluded.timestamp>0 THEN excluded.timestamp ELSE videos.timestamp END""",
            (v.id, v.url, v.title, v.timestamp, json.dumps(seed, ensure_ascii=False)))
        self.db.commit()

    def reconcile(self):
        for row in self.db.execute("SELECT id,filename,bytes FROM videos WHERE state='done'").fetchall():
            path = self.folder / row["filename"]
            if not path.is_file() or path.stat().st_size != row["bytes"]:
                self.db.execute("UPDATE videos SET state='pending',attempts=0,ready=0 WHERE id=?", (row["id"],))
        # A new explicit run may retry previously failed entries, once per run.
        self.db.execute("UPDATE videos SET state='pending',attempts=0,ready=0 WHERE state='failed'")
        self.db.commit()

    def claim(self):
        row = self.db.execute("SELECT * FROM videos WHERE state='pending' AND ready<=? ORDER BY timestamp DESC LIMIT 1",
                              (time.time(),)).fetchone()
        if row:
            self.db.execute("UPDATE videos SET state='active',attempts=attempts+1 WHERE id=?", (row["id"],))
            self.db.commit()
            return dict(row)

    def reset(self, id: str):
        self.db.execute("UPDATE videos SET state='pending',attempts=max(0,attempts-1) WHERE id=?", (id,))
        self.db.commit()

    def fail(self, id: str, error: str, delay: float, max_attempts: int = 4, code: str = "source"):
        self.db.execute("""UPDATE videos SET state=CASE WHEN attempts>=? THEN 'failed' ELSE 'pending' END,
            error=?,ready=?,error_code=? WHERE id=?""", (max_attempts, error, time.time() + delay, code, id))
        self.db.commit()

    def done(self, id: str, result: dict):
        self.db.execute("""UPDATE videos SET state='done',error='',error_code='',filename=?,bytes=?,sha256=?,
            width=?,height=?,provenance=? WHERE id=?""",
            (result["filename"], result["bytes"], result["sha256"], result["width"], result["height"], result["provenance"], id))
        self.db.commit()

    def counts(self):
        counts = {"pending": 0, "active": 0, "done": 0, "failed": 0, "unsupported": 0}
        counts.update(dict(self.db.execute("SELECT state,count(*) FROM videos GROUP BY state")))
        return counts

    def unsupported(self, id: str):
        self.db.execute("UPDATE videos SET state='unsupported',error='Bài ảnh; ngoài phạm vi video' WHERE id=?", (id,))
        self.db.commit()

    def export(self):
        target = self.folder / "ket-qua.csv"
        with target.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "link", "trang_thai", "file", "bytes", "width", "height", "sha256", "nguon", "loi"])
            for row in self.db.execute("SELECT id,url,state,filename,bytes,width,height,sha256,provenance,error FROM videos"):
                # Prevent spreadsheet formula evaluation for externally sourced text.
                writer.writerow(["'" + str(v) if str(v).startswith(("=", "+", "-", "@")) else v for v in row])
        return target

    def close(self):
        self.db.close()
