from __future__ import annotations

from typing import Dict, Any, List, Optional
from threading import RLock

# demo 环境内存会话；生产请替换为数据库或 KV 存储
_CONV: Dict[str, Dict[str, Any]] = {}
_LOCK = RLock()


def get_conv(cid: str) -> Optional[Dict[str, Any]]:
    """读取会话（只读引用；修改请用 set/append/clear 等封装函数）"""
    with _LOCK:
        return _CONV.get(cid)


def set_conv(cid: str, data: Dict[str, Any]) -> None:
    """
    写入/覆盖会话。
    约定字段：
      - pinned: str     固定的 system prompt（或上下文）字符串
      - history: List[Dict{role, content}]
      - kb_index_dir: Optional[str]
    """
    with _LOCK:
        # 兜底：确保基础结构存在
        if "history" not in data or not isinstance(data["history"], list):
            data["history"] = []
        if "pinned" not in data:
            data["pinned"] = ""
        _CONV[cid] = data


def append_history(cid: str, role: str, content: str) -> None:
    """在会话尾部追加一条消息；若会话不存在将抛出 KeyError。"""
    with _LOCK:
        if cid not in _CONV:
            raise KeyError(f"conversation not found: {cid}")
        _CONV[cid]["history"].append({"role": role, "content": content})


# ================= 新增：清空/删除/维护工具 =================

def clear_history(cid: str, *, keep_pinned: bool = True) -> bool:
    """
    清空会话历史消息。
    - keep_pinned=True：保留 pinned、kb_index_dir 等配置，仅把 history=[]。
    - keep_pinned=False：将 pinned 也清空为 '' 。
    返回：是否成功清空（会话不存在返回 False）。
    """
    with _LOCK:
        conv = _CONV.get(cid)
        if not conv:
            return False
        conv["history"] = []
        if not keep_pinned:
            conv["pinned"] = ""
        return True


def delete_conv(cid: str) -> bool:
    """彻底删除会话（包括 pinned/history），返回是否删除成功。"""
    with _LOCK:
        return _CONV.pop(cid, None) is not None


def trim_history(cid: str, max_messages: int) -> int:
    """
    将历史裁剪到最多 max_messages 条，返回裁剪掉的数量（会话不存在返回 -1）。
    常用于内存保护。
    """
    with _LOCK:
        conv = _CONV.get(cid)
        if not conv:
            return -1
        hist: List[Dict[str, Any]] = conv.get("history", [])
        excess = max(0, len(hist) - max_messages)
        if excess > 0:
            conv["history"] = hist[-max_messages:]
        return excess


def list_conv_ids() -> List[str]:
    """调试用：列出当前内存中的所有会话 ID。"""
    with _LOCK:
        return list(_CONV.keys())