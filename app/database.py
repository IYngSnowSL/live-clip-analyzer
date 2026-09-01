"""SQLite 连接与初始化。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH: str | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    video_path TEXT NOT NULL,
    danmaku_path TEXT,
    offset_seconds REAL DEFAULT 0,
    output_languages TEXT DEFAULT '["zh","en"]',
    status TEXT DEFAULT 'pending',
    progress INTEGER DEFAULT 0,
    message TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS scenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    scene_index INTEGER NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    title_zh TEXT,
    title_en TEXT,
    summary_zh TEXT,
    summary_en TEXT,
    visual_summary TEXT,
    asr_text TEXT,
    danmaku_count INTEGER DEFAULT 0,
    danmaku_heat REAL DEFAULT 0,
    danmaku_emotion REAL DEFAULT 0,
    danmaku_keywords TEXT,
    fun_score REAL,
    highlight_score REAL,
    final_score REAL,
    rank TEXT,
    quote TEXT,
    quote_start REAL,
    quote_end REAL,
    quote_reason_zh TEXT,
    quote_reason_en TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(task_id, scene_index)
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    type TEXT NOT NULL,
    start REAL,
    end REAL,
    title_zh TEXT,
    title_en TEXT,
    score REAL,
    reason_zh TEXT,
    reason_en TEXT,
    keywords TEXT,
    reviewed INTEGER DEFAULT 0,
    review_start REAL,
    review_end REAL,
    review_title TEXT,
    review_score REAL,
    review_rank TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS topic_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    topic_index INTEGER NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    title_zh TEXT,
    title_en TEXT,
    summary_zh TEXT,
    summary_en TEXT,
    keywords TEXT,
    score REAL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(task_id, topic_index)
);
"""


def init_db(db_path: str | Path) -> None:
    global DB_PATH
    DB_PATH = str(db_path)
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_conn() -> sqlite3.Connection:
    if DB_PATH is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
