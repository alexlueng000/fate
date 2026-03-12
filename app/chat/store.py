from __future__ import annotations

import json
import os
from threading import RLock
from typing import Dict, Any, List, Optional

_LOCK = RLock()
_CONV: Dict[str, Dict[str, Any]] = {}          # 内存后备（无 REDIS_URL 时使用）
CONV_TTL = int(os.environ.get("CONV_TTL_SECONDS", "86400"))  # 默认 24h

# ── Redis 单例 ───────────────────────────────────────────────
_redis_client = None


def _get_redis():
    global _redis_client
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        return None
    if _redis_client is None:
        import redis as _redis_lib
        _redis_client = _redis_lib.from_url(
            redis_url, decode_responses=True,
            socket_connect_timeout=3, socket_timeout=3
        )
    return _redis_client


def _key(cid: str) -> str:
    return f"fate:conv:{cid}"


# ── 序列化 / 反序列化 ─────────────────────────────────────────
def _serialize(data: Dict[str, Any]) -> Dict[str, str]:
    out = {}
    for k, v in data.items():
        out[k] = json.dumps(v, ensure_ascii=False) if k == "history" \
                 else ("" if v is None else str(v))
    return out


def _deserialize(raw: Dict[str, str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in raw.items():
        if k == "history":
            out[k] = json.loads(v) if v else []
        elif k in ("user_id", "db_conv_id"):
            out[k] = int(v) if v and v not in ("None", "") else None
        else:
            out[k] = None if v in ("None", "") else v
    return out


# ── 公共 API ──────────────────────────────────────────────────

def get_conv(cid: str) -> Optional[Dict[str, Any]]:
    """读取会话（只读引用；修改请用 set/append/clear 等封装函数）"""
    r = _get_redis()
    if r:
        raw = r.hgetall(_key(cid))
        return _deserialize(raw) if raw else None
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
    if "history" not in data or not isinstance(data["history"], list):
        data["history"] = []
    if "pinned" not in data:
        data["pinned"] = ""
    r = _get_redis()
    if r:
        r.hset(_key(cid), mapping=_serialize(data))
        r.expire(_key(cid), CONV_TTL)
        return
    with _LOCK:
        _CONV[cid] = data


def append_history(cid: str, role: str, content: str) -> None:
    """在会话尾部追加一条消息；若会话不存在将抛出 KeyError。"""
    r = _get_redis()
    if r:
        with _LOCK:                          # 读-改-写 原子保护
            key = _key(cid)
            if not r.exists(key):
                raise KeyError(f"conversation not found: {cid}")
            history = json.loads(r.hget(key, "history") or "[]")
            history.append({"role": role, "content": content})
            r.hset(key, "history", json.dumps(history, ensure_ascii=False))
            r.expire(key, CONV_TTL)
        return
    with _LOCK:
        if cid not in _CONV:
            raise KeyError(f"conversation not found: {cid}")
        _CONV[cid]["history"].append({"role": role, "content": content})


def clear_history(cid: str, *, keep_pinned: bool = True) -> bool:
    """
    清空会话历史消息。
    - keep_pinned=True：保留 pinned、kb_index_dir 等配置，仅把 history=[]。
    - keep_pinned=False：将 pinned 也清空为 '' 。
    返回：是否成功清空（会话不存在返回 False）。
    """
    r = _get_redis()
    if r:
        key = _key(cid)
        if not r.exists(key):
            return False
        r.hset(key, "history", "[]")
        if not keep_pinned:
            r.hset(key, "pinned", "")
        r.expire(key, CONV_TTL)
        return True
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
    r = _get_redis()
    if r:
        return bool(r.delete(_key(cid)))
    with _LOCK:
        return _CONV.pop(cid, None) is not None


def trim_history(cid: str, max_messages: int) -> int:
    """
    将历史裁剪到最多 max_messages 条，返回裁剪掉的数量（会话不存在返回 -1）。
    常用于内存保护。
    """
    r = _get_redis()
    if r:
        with _LOCK:
            key = _key(cid)
            if not r.exists(key):
                return -1
            history = json.loads(r.hget(key, "history") or "[]")
            excess = max(0, len(history) - max_messages)
            if excess:
                r.hset(key, "history", json.dumps(history[-max_messages:], ensure_ascii=False))
                r.expire(key, CONV_TTL)
            return excess
    with _LOCK:
        conv = _CONV.get(cid)
        if not conv:
            return -1
        hist: List[Dict[str, Any]] = conv.get("history", [])
        excess = max(0, len(hist) - max_messages)
        if excess:
            conv["history"] = hist[-max_messages:]
        return excess


def list_conv_ids() -> List[str]:
    """调试用：列出当前内存中的所有会话 ID。"""
    r = _get_redis()
    if r:
        prefix = "fate:conv:"
        return [k[len(prefix):] for k in r.scan_iter(f"{prefix}*")]
    with _LOCK:
        return list(_CONV.keys())
