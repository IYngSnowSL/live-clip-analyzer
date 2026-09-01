"""本地文件浏览接口。

供前端"浏览"按钮打开资源管理器式对话框选择文件路径。
浏览器出于安全限制无法通过 <input type="file"> 拿到本地绝对路径，
因此由本后端枚举文件系统，前端选中后回填路径字符串。
"""
from __future__ import annotations

import os
import string
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/files", tags=["files"])

# 不同用途的文件扩展名过滤
VIDEO_EXTS = {".mp4", ".flv", ".mkv", ".mov", ".avi", ".ts", ".m4v", ".wmv", ".webm", ".m2ts"}
XML_EXTS = {".xml"}


def _list_dir(path: str, allow_exts: set[str] | None) -> dict:
    p = Path(path)
    if not p.is_absolute():
        raise HTTPException(400, "path 必须是绝对路径")
    if not p.exists():
        raise HTTPException(404, f"路径不存在: {path}")
    if not p.is_dir():
        raise HTTPException(400, f"不是目录: {path}")

    dirs: list[dict] = []
    files: list[dict] = []
    try:
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        raise HTTPException(403, "无权限访问该目录")
    except OSError as exc:
        raise HTTPException(500, f"无法读取目录: {exc}")

    for e in entries:
        try:
            is_dir = e.is_dir()
        except OSError:
            continue
        if is_dir:
            dirs.append({"name": e.name, "path": str(e), "type": "dir"})
            continue
        if allow_exts and e.suffix.lower() not in allow_exts:
            continue
        try:
            size = e.stat().st_size
        except OSError:
            size = 0
        files.append({"name": e.name, "path": str(e), "type": "file", "size": size})

    parent = str(p.parent) if str(p.parent) != str(p) else ""
    return {"path": str(p), "parent": parent, "dirs": dirs, "files": files}


@router.get("/drives")
async def list_drives():
    """列出磁盘根节点：Windows 返回盘符列表，POSIX 返回根目录内容。"""
    if os.name == "nt":
        drives = []
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                drives.append({"name": root, "path": root, "type": "dir"})
        return {"path": "", "parent": "", "dirs": drives, "files": []}
    return _list_dir("/", None)


@router.get("/ls")
async def list_path(path: str, filter: str = "all"):
    """列出指定目录。filter 取值：all / video / xml。"""
    if filter == "video":
        allow = VIDEO_EXTS
    elif filter == "xml":
        allow = XML_EXTS
    else:
        allow = None
    return _list_dir(path, allow)
