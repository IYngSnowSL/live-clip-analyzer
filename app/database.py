"""SQLite 连接与初始化。

推倒重建后（ADR-0006）的数据模型只有两张业务表：
- tasks：分析任务
- axles：打轴结果（唯一产物表）
旧设计的 scenes / topic_segments / candidates 表在启动时清理。
"""
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
    status TEXT DEFAULT 'pending',
    progress INTEGER DEFAULT 0,
    message TEXT DEFAULT '',
    srt_path TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS axles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    axle_index INTEGER NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    title TEXT,
    reason TEXT,
    score REAL,
    danmaku_peaks TEXT,
    reviewed INTEGER DEFAULT 0,
    review_start REAL,
    review_end REAL,
    review_title TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(task_id, axle_index)
);

-- 旧设计遗留表：推倒重建后废弃（代码不再引用），启动时清理
DROP TABLE IF EXISTS scenes;
DROP TABLE IF EXISTS topic_segments;
DROP TABLE IF EXISTS candidates;
"""


def init_db(db_path: str | Path) -> None:
    global DB_PATH
    DB_PATH = str(db_path)
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        # 迁移：旧库补列（v0.4.0 字幕、v0.4.2 弹幕峰值）
        task_cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)")]
        if "srt_path" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN srt_path TEXT")
        axle_cols = [r[1] for r in conn.execute("PRAGMA table_info(axles)")]
        if "danmaku_peaks" not in axle_cols:
            conn.execute("ALTER TABLE axles ADD COLUMN danmaku_peaks TEXT")
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
