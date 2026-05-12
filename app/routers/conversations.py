"""
对话历史 CRUD — 供历史记录页使用。
支持八字 / 六爻两种类型的会话列表、详情与删除。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user_or_401
from app.models.chat import Conversation, Message

router = APIRouter(prefix="/conversations", tags=["conversations"])


# ===== Response schemas =====

class HexagramSummary(BaseModel):
    hexagram_id: str
    main_gua: Optional[str]
    change_gua: Optional[str]
    question: str


class ConversationListItem(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    last_user_message: Optional[str]
    last_assistant_preview: Optional[str]
    bazi_summary: Optional[str] = None   # 八字才有，格式 "丙午·癸巳·庚辰·癸未"
    hexagram: Optional[HexagramSummary] = None  # 六爻才有


class ConversationListResp(BaseModel):
    items: List[ConversationListItem]
    total: int
    has_more: bool


class MessageItem(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


class ConversationDetailResp(BaseModel):
    id: int
    type: Literal["bazi", "liuyao"]
    title: str
    created_at: datetime
    updated_at: datetime
    messages: List[MessageItem]
    profile: Optional[dict] = None       # 八字才有（命盘快照）
    profile_changed: bool = False        # 命盘是否已被用户修改过
    hexagram: Optional[dict] = None      # 六爻才有


class DeleteConversationsResp(BaseModel):
    deleted: int


# ===== 工具函数 =====

def _four_pillars_summary(bazi_chart_snapshot: Optional[dict]) -> Optional[str]:
    """从命盘快照提取 '年·月·日·时' 四柱摘要（每柱取前两字）。"""
    if not bazi_chart_snapshot:
        return None
    try:
        mingpan = bazi_chart_snapshot.get("mingpan", bazi_chart_snapshot)
        fp = mingpan.get("four_pillars", {})
        parts = []
        for key in ("year", "month", "day", "hour"):
            pillar = fp.get(key, {})
            stem = pillar.get("stem", "")
            branch = pillar.get("branch", "")
            parts.append(f"{stem}{branch}"[:2] if stem or branch else "?")
        return "·".join(parts) if any(p != "?" for p in parts) else None
    except Exception:
        return None


def _preview(text: Optional[str], limit: int = 60) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    return text[:limit] + "…" if len(text) > limit else text


def _safe_user_message(text: Optional[str]) -> Optional[str]:
    """Return a user-facing version of persisted user content."""
    if not text:
        return None

    content = text.strip()
    if not content:
        return None

    if content.startswith("我的命盘信息如下"):
        return None

    leak_markers = (
        "system prompt",
        "系统提示",
        "系统prompt",
        "需引导用户",
        "结合原局",
        "用子平和盲派深度分析",
        "请基于当前命盘",
        "本命盘锚点",
        "重要规则：",
    )
    prompt_like = any(marker in content for marker in leak_markers)
    if prompt_like:
        quick_prompt_rules = [
            (("正缘人物画像",), "正缘人物画像分析"),
            (("人物画像",), "人物画像分析"),
            (("性格", "优势"), "性格特征分析"),
            (("事业",), "事业建议分析"),
            (("财运",), "财运分析"),
            (("健康",), "健康分析"),
            (("正缘应期",), "正缘应期分析"),
            (("流年应期概率最高",), "正缘应期分析"),
        ]
        for keywords, label in quick_prompt_rules:
            if all(keyword in content for keyword in keywords):
                return label

    if any(marker in content for marker in leak_markers):
        return "快捷分析"

    return content


def _conversation_type_query(
    user_id: int,
    type: Literal["bazi", "liuyao", "all"],
):
    query = select(Conversation).where(Conversation.user_id == user_id)
    if type == "bazi":
        return query.where(
            Conversation.profile_id.is_not(None),
            Conversation.liuyao_hexagram_id.is_(None),
        )
    if type == "liuyao":
        return query.where(Conversation.liuyao_hexagram_id.is_not(None))
    return query


# ===== 路由 =====

@router.get("", response_model=ConversationListResp)
def list_conversations(
    type: Literal["bazi", "liuyao"] = Query(..., description="会话类型"),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_or_401),
):
    # 按类型过滤
    base_q = _conversation_type_query(user_id, type)

    total = db.scalar(
        select(func.count()).select_from(base_q.subquery())
    ) or 0

    rows: List[Conversation] = db.scalars(
        base_q.order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items: List[ConversationListItem] = []
    for conv in rows:
        # 取最后一条可展示的 user / assistant 消息预览。
        user_messages = db.scalars(
            select(Message.content)
            .where(Message.conversation_id == conv.id, Message.role == "user")
            .order_by(Message.id.desc())
            .limit(10)
        ).all()
        last_user = next(
            (safe for text in user_messages if (safe := _safe_user_message(text))),
            None,
        )
        last_asst = db.scalar(
            select(Message.content)
            .where(Message.conversation_id == conv.id, Message.role == "assistant")
            .order_by(Message.id.desc())
            .limit(1)
        )

        hexagram_summary: Optional[HexagramSummary] = None
        if type == "liuyao" and conv.liuyao_hexagram_id:
            from app.models.liuyao import LiuyaoHexagram
            hx = db.get(LiuyaoHexagram, conv.liuyao_hexagram_id)
            if hx:
                hexagram_summary = HexagramSummary(
                    hexagram_id=hx.hexagram_id,
                    main_gua=hx.main_gua,
                    change_gua=hx.change_gua,
                    question=hx.question or "",
                )

        items.append(ConversationListItem(
            id=conv.id,
            title=conv.title,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            last_user_message=_preview(last_user),
            last_assistant_preview=_preview(last_asst),
            bazi_summary=_four_pillars_summary(conv.bazi_chart_snapshot) if type == "bazi" else None,
            hexagram=hexagram_summary,
        ))

    return ConversationListResp(
        items=items,
        total=total,
        has_more=(offset + limit) < total,
    )


@router.delete("", response_model=DeleteConversationsResp)
def delete_conversations(
    type: Literal["bazi", "liuyao", "all"] = Query(..., description="要清空的会话类型"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_or_401),
):
    rows = db.scalars(_conversation_type_query(user_id, type)).all()
    deleted = len(rows)
    for conv in rows:
        db.delete(conv)
    db.commit()
    return DeleteConversationsResp(deleted=deleted)


@router.get("/{conversation_id}", response_model=ConversationDetailResp)
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_or_401),
):
    conv = db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")

    conv_type: Literal["bazi", "liuyao"] = (
        "liuyao" if conv.liuyao_hexagram_id else "bazi"
    )

    # 消息列表（按 id 升序）
    msgs = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
    ).all()

    message_items: List[MessageItem] = []
    for m in msgs:
        content = m.content
        if m.role == "user":
            safe_content = _safe_user_message(m.content)
            if not safe_content:
                continue
            content = safe_content
        elif m.role == "system":
            continue

        message_items.append(
            MessageItem(id=m.id, role=m.role, content=content, created_at=m.created_at)
        )

    profile_data: Optional[dict] = None
    profile_changed = False
    hexagram_data: Optional[dict] = None

    if conv_type == "bazi":
        # 返回快照，而非 live profile，保证历史会话上下文自洽
        profile_data = {"bazi_chart": conv.bazi_chart_snapshot} if conv.bazi_chart_snapshot else None

        # 检测命盘是否已被修改
        if conv.profile_id and conv.bazi_chart_snapshot:
            from app.models.profile import UserProfile
            live_profile = db.get(UserProfile, conv.profile_id)
            if live_profile and live_profile.bazi_chart != conv.bazi_chart_snapshot:
                profile_changed = True
    else:
        if conv.liuyao_hexagram_id:
            from app.models.liuyao import LiuyaoHexagram
            from app.routers.liuyao import HexagramDetailResponse
            hx = db.get(LiuyaoHexagram, conv.liuyao_hexagram_id)
            if hx:
                # 复用 HexagramDetailResponse 序列化，保证 lines/change_lines/ganzhi 等
                # 完整字段返回，前端 LiuyaoPage 的 setResult 可直接使用
                hexagram_data = HexagramDetailResponse.model_validate(hx).model_dump(mode="json")

    return ConversationDetailResp(
        id=conv.id,
        type=conv_type,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=message_items,
        profile=profile_data,
        profile_changed=profile_changed,
        hexagram=hexagram_data,
    )


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_or_401),
):
    conv = db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(conv)
    db.commit()
