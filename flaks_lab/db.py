"""SQLite: piezas, trabajos (una pieza en un motor), estado de motores, logs y configuración."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import config

_lock = threading.RLock()
_db_path: Path = config.DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pieces (
    id TEXT PRIMARY KEY,
    client TEXT NOT NULL,
    fecha TEXT NOT NULL,
    fila INTEGER,
    slides TEXT NOT NULL,
    referencia TEXT,
    que_tomar TEXT,
    plantilla TEXT,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    piece_id TEXT NOT NULL,
    engine TEXT NOT NULL,
    client TEXT NOT NULL,
    fecha TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL,           -- en_cola | procesando | listo | error | esperando_manual | cancelado
    step TEXT,
    simulated INTEGER DEFAULT 0,
    attempts INTEGER DEFAULT 0,
    run_id INTEGER,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_s REAL,
    error TEXT,
    output_dir TEXT,
    formats TEXT,
    cost_usd REAL DEFAULT 0,
    usage TEXT,
    review TEXT DEFAULT 'pendiente',  -- pendiente | aprobado | descartado
    score_design INTEGER,
    score_text INTEGER,
    score_brand INTEGER,
    ig_metrics TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_engine_status ON jobs(engine, status);
CREATE INDEX IF NOT EXISTS idx_jobs_piece ON jobs(piece_id);
CREATE TABLE IF NOT EXISTS engine_state (
    engine TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0,
    paused_until TEXT,
    pause_reason TEXT,
    deleted INTEGER NOT NULL DEFAULT 0,
    day TEXT,
    day_count INTEGER DEFAULT 0,
    day_cap INTEGER,
    since_break INTEGER DEFAULT 0,
    break_every INTEGER
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    trigger TEXT,
    client TEXT,
    step TEXT,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    engine TEXT,
    job_id INTEGER,
    run_id INTEGER,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    client TEXT PRIMARY KEY,
    tab TEXT,
    status TEXT,
    mode TEXT,
    rows INTEGER,
    last_sync TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    engine TEXT,
    message TEXT NOT NULL,
    dismissed INTEGER DEFAULT 0
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def set_path(path: Path) -> None:
    """Permite usar otra base (tests)."""
    global _db_path
    _db_path = Path(path)


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    with _lock:
        c = sqlite3.connect(_db_path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()


def init() -> None:
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)
        # columnas agregadas después de la primera versión
        if "plantilla" not in [r[1] for r in c.execute("PRAGMA table_info(pieces)")]:
            c.execute("ALTER TABLE pieces ADD COLUMN plantilla TEXT")


def query(sql: str, params: tuple | list = ()) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def one(sql: str, params: tuple | list = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple | list = ()) -> int:
    with conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid or cur.rowcount


# ---------- configuración ----------

def get_settings() -> dict:
    row = one("SELECT data FROM settings WHERE id = 1")
    return config.merge_defaults(json.loads(row["data"]) if row else None)


def save_settings(data: dict) -> dict:
    merged = config.merge_defaults(data)
    execute(
        "INSERT INTO settings (id, data) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
        (json.dumps(merged, ensure_ascii=False),),
    )
    return merged


# ---------- logs y alertas ----------

def log(message: str, level: str = "info", engine: str | None = None,
        job_id: int | None = None, run_id: int | None = None) -> None:
    execute(
        "INSERT INTO logs (ts, level, engine, job_id, run_id, message) VALUES (?, ?, ?, ?, ?, ?)",
        (now(), level, engine, job_id, run_id, message),
    )


def alert(message: str, engine: str | None = None) -> None:
    execute("INSERT INTO alerts (ts, engine, message) VALUES (?, ?, ?)", (now(), engine, message))
    log(message, "alerta", engine)


def update_job(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in fields.values()]
    execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*values, job_id))
