"""SQLite persistence for request history and hardware samples.

Design notes:
- Single connection guarded by a lock; writes are funnelled through a
  dedicated writer thread + queue so HTTP handlers never block on disk I/O.
- WAL mode so readers don't contend with the writer.
- Only statistical metadata is stored. Prompt / completion text is NEVER
  written to disk (privacy requirement).
"""
from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("ollama-monitor.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at               REAL NOT NULL,
    model                    TEXT,
    stream                   INTEGER DEFAULT 0,
    status                   TEXT,
    prompt_tokens            INTEGER DEFAULT 0,
    completion_tokens        INTEGER DEFAULT 0,
    total_tokens             INTEGER DEFAULT 0,
    prompt_eval_duration_ns  INTEGER,
    eval_duration_ns         INTEGER,
    total_duration_ns        INTEGER,
    load_duration_ns         INTEGER,
    tokens_per_sec           REAL,
    time_to_first_token_ms   REAL,
    error                    TEXT,
    client                   TEXT,
    detail                   TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_created ON requests(created_at);
CREATE INDEX IF NOT EXISTS idx_requests_model   ON requests(model);

CREATE TABLE IF NOT EXISTS hardware (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   REAL NOT NULL,
    gpu_util     REAL,
    gpu_mem_used REAL,
    gpu_mem_total REAL,
    gpu_temp     REAL,
    gpu_power    REAL,
    cpu_util     REAL,
    mem_total    REAL,
    mem_used     REAL
);
CREATE INDEX IF NOT EXISTS idx_hardware_created ON hardware(created_at);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._closed = False
        self._conn = self._open()
        self._writer = threading.Thread(target=self._writer_loop, daemon=True, name="db-writer")
        self._writer.start()

    def _open(self) -> sqlite3.Connection:
        """Open the database; on corruption, back it up and start fresh."""
        try:
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.executescript(SCHEMA)
            conn.commit()
            return conn
        except sqlite3.DatabaseError as exc:
            try:
                conn.close()
            except Exception:
                pass
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = self.path.with_name(f"{self.path.stem}.corrupt-{stamp}.db")
            try:
                self.path.replace(backup)
                logger.error(
                    "Database %s is corrupted (%s). Backed up to %s and created a fresh database.",
                    self.path, exc, backup,
                )
            except OSError:
                logger.error(
                    "Database %s is corrupted (%s) and could not be moved. Creating a fresh database in place.",
                    self.path, exc,
                )
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.executescript(SCHEMA)
            conn.commit()
            return conn

    # -- writer ------------------------------------------------------------
    def _writer_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            op, args = item
            try:
                with self._lock:
                    if op == "insert_request":
                        self._insert_request_locked(args[0])
                    elif op == "insert_hardware":
                        self._insert_hardware_locked(args[0])
                    elif op == "exec":
                        args[0]()
                    self._conn.commit()
            except Exception:
                # Never let a write error kill the writer thread.
                pass
            finally:
                self._queue.task_done()

    def _insert_request_locked(self, r: dict) -> None:
        self._conn.execute(
            """INSERT INTO requests
               (created_at, model, stream, status, prompt_tokens, completion_tokens,
                total_tokens, prompt_eval_duration_ns, eval_duration_ns,
                total_duration_ns, load_duration_ns, tokens_per_sec,
                time_to_first_token_ms, error, client, detail)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                r.get("created_at", time.time()),
                r.get("model"),
                1 if r.get("stream") else 0,
                r.get("status"),
                int(r.get("prompt_tokens", 0) or 0),
                int(r.get("completion_tokens", 0) or 0),
                int(r.get("total_tokens", 0) or 0),
                r.get("prompt_eval_duration_ns"),
                r.get("eval_duration_ns"),
                r.get("total_duration_ns"),
                r.get("load_duration_ns"),
                r.get("tokens_per_sec"),
                r.get("time_to_first_token_ms"),
                r.get("error"),
                r.get("client"),
                json.dumps(r.get("detail", {}), ensure_ascii=False),
            ),
        )

    def _insert_hardware_locked(self, h: dict) -> None:
        self._conn.execute(
            """INSERT INTO hardware
               (created_at, gpu_util, gpu_mem_used, gpu_mem_total, gpu_temp,
                gpu_power, cpu_util, mem_total, mem_used)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                h.get("created_at", time.time()),
                h.get("gpu_util"),
                h.get("gpu_mem_used"),
                h.get("gpu_mem_total"),
                h.get("gpu_temp"),
                h.get("gpu_power"),
                h.get("cpu_util"),
                h.get("mem_total"),
                h.get("mem_used"),
            ),
        )

    def insert_request(self, record: dict) -> None:
        if self._closed:
            return
        self._queue.put(("insert_request", (record,)))

    def insert_hardware(self, record: dict) -> None:
        if self._closed:
            return
        self._queue.put(("insert_hardware", (record,)))

    def flush(self) -> None:
        """Block until all queued writes are applied (used before close/tests)."""
        self._queue.join()

    # -- readers -----------------------------------------------------------
    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.fetchall()

    def summary(self) -> dict:
        rows = self._query(
            """SELECT
                 COUNT(*)                                      AS total_requests,
                 COALESCE(SUM(prompt_tokens), 0)               AS prompt_tokens,
                 COALESCE(SUM(completion_tokens), 0)           AS completion_tokens,
                 COALESCE(SUM(total_tokens), 0)                AS total_tokens
               FROM requests WHERE status = 'success'"""
        )
        r = dict(rows[0])
        today = time.strftime("%Y-%m-%d")
        t = self._query(
            """SELECT
                 COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
                 COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                 COALESCE(SUM(total_tokens), 0)      AS total_tokens,
                 COUNT(*)                            AS total_requests
               FROM requests
               WHERE status = 'success' AND date(created_at, 'unixepoch', 'localtime') = ?""",
            (today,),
        )
        r["today"] = dict(t[0])
        return r

    def avg_tps(self) -> Optional[float]:
        rows = self._query(
            """SELECT COALESCE(SUM(completion_tokens), 0) AS c,
                      COALESCE(SUM(eval_duration_ns), 0) AS e
               FROM requests WHERE status = 'success'"""
        )
        if not rows or not rows[0]["e"]:
            return None
        return round(rows[0]["c"] / (rows[0]["e"] / 1_000_000_000), 2)

    def latest_success(self) -> Optional[dict]:
        rows = self._query(
            """SELECT * FROM requests WHERE status = 'success'
               ORDER BY created_at DESC LIMIT 1"""
        )
        return dict(rows[0]) if rows else None

    def per_model(self) -> list[dict]:
        rows = self._query(
            """SELECT model,
                 COUNT(*)                             AS requests,
                 COALESCE(SUM(prompt_tokens), 0)      AS prompt_tokens,
                 COALESCE(SUM(completion_tokens), 0)  AS completion_tokens,
                 COALESCE(SUM(total_tokens), 0)       AS total_tokens,
                 AVG(tokens_per_sec)                  AS avg_tps
               FROM requests
               WHERE status = 'success' AND model IS NOT NULL
               GROUP BY model ORDER BY total_tokens DESC"""
        )
        return [dict(x) for x in rows]

    def daily(self, limit: int = 30) -> list[dict]:
        rows = self._query(
            """SELECT date(created_at, 'unixepoch', 'localtime') AS day,
                 COALESCE(SUM(prompt_tokens), 0)      AS prompt_tokens,
                 COALESCE(SUM(completion_tokens), 0)  AS completion_tokens,
                 COALESCE(SUM(total_tokens), 0)       AS total_tokens,
                 COUNT(*)                             AS requests
               FROM requests
               WHERE status = 'success'
               GROUP BY day ORDER BY day DESC LIMIT ?""",
            (limit,),
        )
        return [dict(x) for x in rows]

    def list_requests(
        self,
        model: Optional[str] = None,
        date: Optional[str] = None,
        q: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict:
        where = ["1=1"]
        params: list[Any] = []
        if model:
            where.append("model = ?")
            params.append(model)
        if date:
            where.append("date(created_at, 'unixepoch', 'localtime') = ?")
            params.append(date)
        if q:
            where.append("(model LIKE ? OR status LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        cond = " AND ".join(where)
        total = self._query(f"SELECT COUNT(*) AS n FROM requests WHERE {cond}", tuple(params))[0]["n"]
        offset = (page - 1) * limit
        rows = self._query(
            f"""SELECT * FROM requests WHERE {cond}
                ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            tuple(params + [limit, offset]),
        )
        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [dict(x) for x in rows],
        }

    def get_request(self, rid: int) -> Optional[dict]:
        rows = self._query("SELECT * FROM requests WHERE id = ?", (rid,))
        return dict(rows[0]) if rows else None

    def distinct_models(self) -> list[str]:
        rows = self._query(
            "SELECT DISTINCT model FROM requests WHERE model IS NOT NULL ORDER BY model"
        )
        return [x["model"] for x in rows]

    def clear_requests(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM requests")
            n = cur.rowcount
            self._conn.commit()
            return n

    def prune_old(self, days: int) -> int:
        """Delete request/hardware records older than `days` (0/negative = keep all)."""
        if days is None or int(days) <= 0:
            return 0
        cutoff = time.time() - int(days) * 86400
        with self._lock:
            a = self._conn.execute("DELETE FROM requests WHERE created_at < ?", (cutoff,)).rowcount
            b = self._conn.execute("DELETE FROM hardware WHERE created_at < ?", (cutoff,)).rowcount
            self._conn.commit()
            return a + b

    def recent_hardware(self, seconds: int = 3600, max_rows: int = 1000) -> list[dict]:
        cutoff = time.time() - seconds
        rows = self._query(
            """SELECT created_at, gpu_util, gpu_mem_used, gpu_mem_total, gpu_temp,
                      gpu_power, cpu_util, mem_total, mem_used
               FROM hardware WHERE created_at >= ?
               ORDER BY created_at ASC LIMIT ?""",
            (cutoff, max_rows),
        )
        return [dict(x) for x in rows]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put(None)  # sentinel
        self._writer.join(timeout=3)
        with self._lock:
            self._conn.commit()
            self._conn.close()
