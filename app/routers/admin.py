# app/routers/admin.py
from __future__ import annotations

import json
from typing import Optional, Literal, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError, validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db

# 可选：若你项目里已有 get_redis，这里自动引用；没有也可运行（失效缓存会跳过）
try:
    from ..core.redis_dep import get_redis  # 你的项目里若有这个依赖
except Exception:
    async def get_redis():
        return None  # 占位，保证本文件可用

# -----------------------------
# 权限：请替换为你真实的管理员校验
# -----------------------------
def admin_required():
    # TODO: 替换为真实鉴权，例如读取 request.user.is_admin
    is_admin = True
    if not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return True

# -----------------------------
# 配置
# -----------------------------
ALLOWED_KEYS = {"system_prompt", "quick_buttons"}
CACHE_PREFIX = "cfg:"  # Redis 前缀，例如 cfg:system_prompt:v1
CACHE_VER = "v1"

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(admin_required)]
)

# ========== Pydantic Schemas ==========

class ConfigSaveReq(BaseModel):
    key: Literal["system_prompt", "quick_buttons"]
    value_json: dict = Field(..., description="完整配置 JSON")
    comment: Optional[str] = Field(None, max_length=255)

    @validator("value_json")
    def validate_shape(cls, v, values):
        key = values.get("key")
        # 轻量 JSON 结构校验，可按需加严
        if key == "system_prompt":
            if not isinstance(v.get("content"), str) or not v["content"].strip():
                raise ValueError("system_prompt.value_json.content 必须为非空字符串")
        elif key == "quick_buttons":
            items = v.get("items", [])
            if not isinstance(items, list):
                raise ValueError("quick_buttons.value_json.items 必须为数组")
            for i, it in enumerate(items):
                if not isinstance(it.get("label"), str) or not it["label"].strip():
                    raise ValueError(f"items[{i}].label 必须为非空字符串")
                if not isinstance(it.get("prompt"), str) or not it["prompt"].strip():
                    raise ValueError(f"items[{i}].prompt 必须为非空字符串")
                if not isinstance(it.get("order"), int):
                    raise ValueError(f"items[{i}].order 必须为整数")
                if not isinstance(it.get("active"), bool):
                    raise ValueError(f"items[{i}].active 必须为布尔值")
        return v


class ConfigRollbackReq(BaseModel):
    key: Literal["system_prompt", "quick_buttons"]
    version: int = Field(..., ge=1, description="目标历史版本号")
    comment: Optional[str] = Field(None, max_length=255)

# ========== 工具函数 ==========

async def invalidate_cache(r, key: str):
    if not r:
        return
    try:
        await r.delete(f"{CACHE_PREFIX}{key}:{CACHE_VER}")
    except Exception:
        pass

def fetch_current(db: Session, key: str) -> Optional[dict]:
    row = db.execute(
        text("SELECT cfg_key, value_json, version, updated_at, editor_id, comment "
             "FROM app_config WHERE cfg_key=:k AND is_active=1"),
        {"k": key}
    ).mappings().first()
    if not row:
        return None
    return {
        "key": row["cfg_key"],
        "value_json": row["value_json"],
        "version": row["version"],
        "updated_at": row["updated_at"],
        "editor_id": row["editor_id"],
        "comment": row["comment"],
    }

def fetch_revision(db: Session, key: str, version: int) -> Optional[dict]:
    row = db.execute(
        text("SELECT cfg_key, value_json, version, created_at, editor_id, comment "
             "FROM app_config_revisions WHERE cfg_key=:k AND version=:v"),
        {"k": key, "v": version}
    ).mappings().first()
    if not row:
        return None
    return dict(row)

def next_version(db: Session, key: str) -> int:
    row = db.execute(
        text("SELECT COALESCE(MAX(version), 0) AS v FROM app_config_revisions WHERE cfg_key=:k"),
        {"k": key}
    ).mappings().first()
    return int(row["v"] or 0) + 1

def upsert_current(db: Session, key: str, value_json: dict, version: int, editor_id: Optional[int], comment: Optional[str]):
    # app_config 主表：仅保存当前版本
    payload = json.dumps(value_json, ensure_ascii=False)
    db.execute(text(
        "INSERT INTO app_config (cfg_key, value_json, version, is_active, editor_id, comment) "
        "VALUES (:k, CAST(:v AS JSON), :ver, 1, :eid, :cmt) "
        "ON DUPLICATE KEY UPDATE value_json=VALUES(value_json), version=VALUES(version), "
        "is_active=1, editor_id=VALUES(editor_id), comment=VALUES(comment), updated_at=NOW()"
    ), {"k": key, "v": payload, "ver": version, "eid": editor_id, "cmt": comment})

def insert_revision(db: Session, key: str, value_json: dict, version: int, editor_id: Optional[int], comment: Optional[str]):
    payload = json.dumps(value_json, ensure_ascii=False)
    db.execute(text(
        "INSERT INTO app_config_revisions (cfg_key, value_json, version, editor_id, comment) "
        "VALUES (:k, CAST(:v AS JSON), :ver, :eid, :cmt)"
    ), {"k": key, "v": payload, "ver": version, "eid": editor_id, "cmt": comment})

# ========== 管理端接口（改查） ==========

@router.get("/config")
def admin_get_config(
    key: str = Query(..., description="配置项 key"),
    db: Session = Depends(get_db)
):
    if key not in ALLOWED_KEYS:
        raise HTTPException(400, f"不支持的 key：{key}")
    data = fetch_current(db, key)
    if not data:
        raise HTTPException(404, f"未找到配置：{key}")
    return data

@router.get("/config/revisions")
def admin_get_revisions(
    key: str = Query(...),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    if key not in ALLOWED_KEYS:
        raise HTTPException(400, f"不支持的 key：{key}")
    rows = db.execute(text(
        "SELECT cfg_key, version, created_at, editor_id, comment "
        "FROM app_config_revisions WHERE cfg_key=:k "
        "ORDER BY version DESC LIMIT :lim OFFSET :off"
    ), {"k": key, "lim": limit, "off": offset}).mappings().all()
    return [dict(r) for r in rows]

@router.post("/config/save")
async def admin_save_config(
    payload: ConfigSaveReq,
    db: Session = Depends(get_db),
    r = Depends(get_redis)
):
    key = payload.key
    if key not in ALLOWED_KEYS:
        raise HTTPException(400, f"不支持的 key：{key}")

    # 版本号：在历史上 +1
    ver = next_version(db, key)

    # 这里 editor_id 先留空，等你接入 /me 后可以填当前管理员ID
    editor_id = None

    # 写修订历史 + 覆盖当前版本（事务）
    insert_revision(db, key, payload.value_json, ver, editor_id, payload.comment)
    upsert_current(db, key, payload.value_json, ver, editor_id, payload.comment)
    db.commit()

    await invalidate_cache(r, key)
    return {"ok": True, "key": key, "version": ver}

@router.post("/config/rollback")
async def admin_rollback_config(
    payload: ConfigRollbackReq,
    db: Session = Depends(get_db),
    r = Depends(get_redis)
):
    key = payload.key
    if key not in ALLOWED_KEYS:
        raise HTTPException(400, f"不支持的 key：{key}")

    rev = fetch_revision(db, key, payload.version)
    if not rev:
        raise HTTPException(404, f"找不到版本：{key} v{payload.version}")

    # 用历史版本的 value 作为新版本保存（version 继续自增）
    new_version = next_version(db, key)
    editor_id = None
    value_json = rev["value_json"]

    insert_revision(db, key, value_json, new_version, editor_id, payload.comment or f"rollback from v{payload.version}")
    upsert_current(db, key, value_json, new_version, editor_id, payload.comment or f"rollback from v{payload.version}")
    db.commit()

    await invalidate_cache(r, key)
    return {"ok": True, "key": key, "version": new_version}
