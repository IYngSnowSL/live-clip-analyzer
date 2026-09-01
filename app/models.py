"""数据访问层：任务 / 场景 / 候选。"""
from __future__ import annotations

import json
import uuid
from typing import Any

from .database import get_conn


def _row_to_dict(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


# ---------------- 任务 ----------------

def create_task(video_path: str, danmaku_path: str | None, offset_seconds: float,
                output_languages: list[str]) -> dict[str, Any]:
    task_id = uuid.uuid4().hex[:12]
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO tasks (id, video_path, danmaku_path, offset_seconds, output_languages) "
            "VALUES (?,?,?,?,?)",
            (task_id, video_path, danmaku_path, offset_seconds,
             json.dumps(output_languages, ensure_ascii=False)),
        )
        conn.commit()
        return get_task(task_id)
    finally:
        conn.close()


def get_task(task_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def list_tasks() -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC, rowid DESC").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def delete_task(task_id: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM candidates WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM scenes WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
    finally:
        conn.close()


def update_task(task_id: str, **fields: Any) -> None:
    if not fields:
        return
    keys = list(fields)
    sql = "UPDATE tasks SET " + ", ".join(f"{k}=?" for k in keys) + ", updated_at=datetime('now','localtime') WHERE id=?"
    conn = get_conn()
    try:
        conn.execute(sql, [fields[k] for k in keys] + [task_id])
        conn.commit()
    finally:
        conn.close()


def mark_interrupted_tasks() -> int:
    """启动时把上次进程遗留的 running/pending 任务标记为失败，返回受影响行数。"""
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE tasks SET status='failed', message='服务重启，任务中断', "
            "updated_at=datetime('now','localtime') WHERE status IN ('running','pending')"
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ---------------- 场景 ----------------

SCENE_FIELDS = [
    "task_id", "scene_index", "start", "end", "title_zh", "title_en",
    "summary_zh", "summary_en", "visual_summary", "asr_text",
    "danmaku_count", "danmaku_heat", "danmaku_emotion", "danmaku_keywords",
    "fun_score", "highlight_score", "final_score", "rank",
    "quote", "quote_start", "quote_end", "quote_reason_zh", "quote_reason_en",
]


def save_scenes(task_id: str, scenes: list[dict[str, Any]]) -> None:
    """按 (task_id, scene_index) 插入或替换场景。"""
    conn = get_conn()
    try:
        for sc in scenes:
            values = []
            for f in SCENE_FIELDS:
                val = sc.get(f)
                if isinstance(val, (list, dict)):
                    val = json.dumps(val, ensure_ascii=False)
                values.append(val)
            placeholders = ",".join("?" for _ in SCENE_FIELDS)
            sql = (
                f"INSERT OR REPLACE INTO scenes ({','.join(SCENE_FIELDS)}) "
                f"VALUES ({placeholders})"
            )
            conn.execute(sql, values)
        conn.commit()
    finally:
        conn.close()


def get_scenes(task_id: str) -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM scenes WHERE task_id=? ORDER BY scene_index ASC", (task_id,)
        ).fetchall()
        return [_scene_from_row(_row_to_dict(r)) for r in rows]
    finally:
        conn.close()


def _scene_from_row(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("danmaku_keywords"):
        try:
            row["danmaku_keywords"] = json.loads(row["danmaku_keywords"])
        except Exception:
            row["danmaku_keywords"] = []
    return row


# ---------------- 候选 ----------------

CANDIDATE_FIELDS = [
    "task_id", "type", "start", "end", "title_zh", "title_en",
    "score", "reason_zh", "reason_en", "keywords",
]


def save_candidates(task_id: str, candidates: list[dict[str, Any]]) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM candidates WHERE task_id=?", (task_id,))
        for c in candidates:
            values = []
            for f in CANDIDATE_FIELDS:
                val = c.get(f)
                if isinstance(val, (list, dict)):
                    val = json.dumps(val, ensure_ascii=False)
                values.append(val)
            placeholders = ",".join("?" for _ in CANDIDATE_FIELDS)
            sql = (
                f"INSERT INTO candidates ({','.join(CANDIDATE_FIELDS)}) "
                f"VALUES ({placeholders})"
            )
            conn.execute(sql, values)
        conn.commit()
    finally:
        conn.close()


def get_candidates(task_id: str) -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM candidates WHERE task_id=? ORDER BY type ASC, score DESC", (task_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = _row_to_dict(r)
            if d.get("keywords"):
                try:
                    d["keywords"] = json.loads(d["keywords"])
                except Exception:
                    d["keywords"] = []
            result.append(d)
        return result
    finally:
        conn.close()


def update_candidate_review(task_id: str, candidate_id: int, **fields: Any) -> None:
    allowed = {"review_start", "review_end", "review_title", "review_score", "review_rank", "reviewed"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    fields["reviewed"] = 1
    keys = list(fields)
    sql = "UPDATE candidates SET " + ", ".join(f"{k}=?" for k in keys) + " WHERE id=? AND task_id=?"
    conn = get_conn()
    try:
        conn.execute(sql, [fields[k] for k in keys] + [candidate_id, task_id])
        conn.commit()
    finally:
        conn.close()
