# app/chat/store.py
from typing import Dict, Any

# demo 环境内存会话；生产请替换为数据库
_CONV: Dict[str, Dict[str, Any]] = {}

def get_conv(cid: str) -> Dict[str, Any] | None:
    return _CONV.get(cid)

def set_conv(cid: str, data: Dict[str, Any]) -> None:
    _CONV[cid] = data

def append_history(cid: str, role: str, content: str) -> None:
    _CONV[cid]["history"].append({"role": role, "content": content})
