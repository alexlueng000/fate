# app/routers/config_public.py
from __future__ import annotations

import json
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db

# 可选 Redis 缓存
try:
    from ..core.redis_dep import get_redis
except Exception:
    async def get_redis():
        return None

CACHE_PREFIX = "cfg:"
CACHE_VER = "v1"

router = APIRouter(prefix="/config", tags=["config"])

def fetch_current(db: Session, key: str) -> dict | None:
    row = db.execute(
        text("SELECT value_json FROM app_config WHERE cfg_key=:k AND is_active=1"),
        {"k": key}
    ).mappings().first()
    return row["value_json"] if row else None

@router.get("/quick_buttons")
async def get_quick_buttons(db: Session = Depends(get_db), r=Depends(get_redis)):
    cache_key = f"{CACHE_PREFIX}quick_buttons:{CACHE_VER}"
    # 先走缓存（如果有）
    if r:
        val = await r.get(cache_key)
        if val:
            try:
                data = json.loads(val)
                return data  # 缓存里已是最终形式
            except Exception:
                pass

    cfg = fetch_current(db, "quick_buttons")
    if not cfg:
        return []  # 没配置就返回空

    items = cfg.get("items", [])
    # 过滤 active，并按 order 排序，只暴露 label/prompt
    items = [it for it in items if it.get("active") is True]
    items.sort(key=lambda x: x.get("order", 0))
    data = [{"label": it.get("label", ""), "prompt": it.get("prompt", "")} for it in items]

    if r:
        await r.set(cache_key, json.dumps(data, ensure_ascii=False), ex=3600)

    return data

@router.get("/system_prompt")
async def get_system_prompt(db: Session = Depends(get_db), r=Depends(get_redis)):
    cache_key = f"{CACHE_PREFIX}system_prompt:{CACHE_VER}"
    if r:
        val = await r.get(cache_key)
        if val:
            try:
                data = json.loads(val)
                return data
            except Exception:
                pass

    cfg = fetch_current(db, "system_prompt")
    if not cfg:
        raise HTTPException(404, "system_prompt 未配置")

    # 返回完整 JSON（包含 content/notes）
    if r:
        await r.set(cache_key, json.dumps(cfg, ensure_ascii=False), ex=3600)
    return cfg
