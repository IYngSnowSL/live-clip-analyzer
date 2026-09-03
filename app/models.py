"""数据访问层：任务 / 轴（axles）。"""
from __future__ import annotations

import json
import uuid
from typing import Any

from .database import get_conn


def _row_to_dict(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


# ---------------- 任务 ----------------

def create_task(video_path: str, danmaku_path: str | None,
                offset_seconds: float) -> dict[str, Any]:
    task_id = uuid.uuid4().hex[:12]
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO tasks (id, video_path, danmaku_path, offset_seconds) "
            "VALUES (?,?,?,?)",
            (task_id, video_path, danmaku_path, offset_seconds),
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
        conn.execute("DELETE FROM axles WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
    finally:
        conn.close()


# update_task 允许写入的列白名单（防注入任意列名）
_TASK_UPDATE_FIELDS = {"status", "progress", "message", "srt_path"}


def update_task(task_id: str, **fields: Any) -> None:
    fields = {k: v for k, v in fields.items() if k in _TASK_UPDATE_FIELDS}
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


# ---------------- 轴（打轴结果） ----------------

AXLE_FIELDS = [
    "task_id", "axle_index", "start", "end", "title", "reason", "score",
    "danmaku_peaks",
]


def save_axles(task_id: str, axles: list[dict[str, Any]]) -> None:
    """按 task 覆盖写入打轴结果。task_id 由参数注入，轴 dict 不携带容器字段。"""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM axles WHERE task_id=?", (task_id,))
        for a in axles:
            values = []
            for f in AXLE_FIELDS:
                val = task_id if f == "task_id" else a.get(f)
                if isinstance(val, (list, dict)):
                    val = json.dumps(val, ensure_ascii=False)
                values.append(val)
            placeholders = ",".join("?" for _ in AXLE_FIELDS)
            sql = f"INSERT INTO axles ({','.join(AXLE_FIELDS)}) VALUES ({placeholders})"
            conn.execute(sql, values)
        conn.commit()
    finally:
        conn.close()


def _parse_axle(row) -> dict[str, Any]:
    d = _row_to_dict(row) or {}
    if d.get("danmaku_peaks"):
        try:
            d["danmaku_peaks"] = json.loads(d["danmaku_peaks"])
        except (TypeError, ValueError):
            d["danmaku_peaks"] = []
    else:
        d["danmaku_peaks"] = []
    return d


def get_axles(task_id: str) -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM axles WHERE task_id=? ORDER BY axle_index ASC", (task_id,)
        ).fetchall()
        return [_parse_axle(r) for r in rows]
    finally:
        conn.close()


def update_axle_review(task_id: str, axle_id: int, **fields: Any) -> None:
    allowed = {"review_start", "review_end", "review_title", "reviewed"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    fields["reviewed"] = 1
    keys = list(fields)
    sql = "UPDATE axles SET " + ", ".join(f"{k}=?" for k in keys) + " WHERE id=? AND task_id=?"
    conn = get_conn()
    try:
        conn.execute(sql, [fields[k] for k in keys] + [axle_id, task_id])
        conn.commit()
    finally:
        conn.close()
