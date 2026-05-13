# app/routers/config_public.py
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db

# Optional Redis cache.
try:
    from ..core.redis_dep import get_redis
except Exception:
    async def get_redis():
        return None

CACHE_PREFIX = "cfg:"
CACHE_VER = "v1"

router = APIRouter(prefix="/config", tags=["config"])

def parse_value_json(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def fetch_current(db: Session, key: str) -> dict | None:
    row = db.execute(
        text("SELECT value_json FROM app_config WHERE cfg_key=:k AND is_active=1"),
        {"k": key}
    ).mappings().first()
    return parse_value_json(row["value_json"]) if row else None


def active_quick_buttons(cfg: dict | None) -> list[dict[str, str]]:
    if not cfg:
        return []

    items = cfg.get("items", [])
    if not isinstance(items, list):
        return []

    active_items = [
        it for it in items
        if isinstance(it, dict) and it.get("active") is True
    ]
    active_items.sort(
        key=lambda x: x.get("order", 0) if isinstance(x.get("order", 0), int) else 0
    )
    return [
        {"label": it.get("label", ""), "prompt": it.get("prompt", "")}
        for it in active_items
        if isinstance(it.get("label"), str) and isinstance(it.get("prompt"), str)
    ]

@router.get("/quick_buttons")
async def get_quick_buttons(db: Session = Depends(get_db), r=Depends(get_redis)):
    cache_key = f"{CACHE_PREFIX}quick_buttons:{CACHE_VER}"
    # Use cache first when available.
    if r:
        val = await r.get(cache_key)
        if val:
            try:
                data = json.loads(val)
                return data
            except Exception:
                pass

    data = active_quick_buttons(fetch_current(db, "quick_buttons"))

    if r:
        await r.set(cache_key, json.dumps(data, ensure_ascii=False), ex=3600)

    return data

@router.get("/liuyao_quick_buttons")
async def get_liuyao_quick_buttons(db: Session = Depends(get_db), r=Depends(get_redis)):
    cache_key = f"{CACHE_PREFIX}liuyao_quick_buttons:{CACHE_VER}"
    if r:
        val = await r.get(cache_key)
        if val:
            try:
                data = json.loads(val)
                return data
            except Exception:
                pass

    data = active_quick_buttons(fetch_current(db, "liuyao_quick_buttons"))

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
        raise HTTPException(404, "system_prompt not configured")

    # Return the full JSON payload, including content and notes.
    if r:
        await r.set(cache_key, json.dumps(cfg, ensure_ascii=False), ex=3600)
    return cfg

@router.get("/bazi_intro")
async def get_bazi_intro(db: Session = Depends(get_db), r=Depends(get_redis)):
    cache_key = f"{CACHE_PREFIX}bazi_intro:{CACHE_VER}"
    if r:
        val = await r.get(cache_key)
        if val:
            try:
                data = json.loads(val)
                return data
            except Exception:
                pass

    cfg = fetch_current(db, "bazi_intro")
    if not cfg:
        raise HTTPException(404, "bazi_intro not configured")

    content = cfg.get("content")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(404, "bazi_intro not configured")

    if r:
        await r.set(cache_key, json.dumps(cfg, ensure_ascii=False), ex=3600)
    return cfg

