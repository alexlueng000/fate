"""
对话历史 CRUD — 供历史记录页使用。
支持八字 / 六爻两种类型的会话列表、详情与删除。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user_or_401
from app.models.chat import Conversation, Message
from app.models.conversation_digest import ConversationDigest
from app.services.conversation_digest import generate_digest

router = APIRouter(prefix="/conversations", tags=["conversations"])


# ===== Response schemas =====

class HexagramSummary(BaseModel):
    hexagram_id: str
    main_gua: Optional[str]
    change_gua: Optional[str]
    question: str


class DigestResponse(BaseModel):
    title: Optional[str] = None
    custom_title: Optional[str] = None
    topic: Optional[str] = None
    question: Optional[str] = None
    summary: Optional[str] = None
    status: str = "empty"
    source_message_id: int = 0
    generated_at: Optional[datetime] = None
    stale: bool = False


class ConversationListItem(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    last_user_message: Optional[str]
    last_assistant_preview: Optional[str]
    bazi_summary: Optional[str] = None   # 八字才有，格式 "丙午·癸巳·庚辰·癸未"
    hexagram: Optional[HexagramSummary] = None  # 六爻才有
    task_context: Optional[Dict[str, Any]] = None
    digest: Optional[DigestResponse] = None


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
    task_context: Optional[Dict[str, Any]] = None


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


def _has_displayable_assistant_message_query():
    """Only show conversations that have saved assistant content."""
    return (
        select(Message.id)
        .where(
            Message.conversation_id == Conversation.id,
            Message.role == "assistant",
            func.length(func.trim(Message.content)) > 0,
        )
        .limit(1)
        .exists()
    )


# ===== 路由 =====

@router.get("", response_model=ConversationListResp)
def list_conversations(
    type: Literal["bazi", "liuyao"] = Query(..., description="会话类型"),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    q: str = Query("", max_length=80),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_or_401),
):
    # 按类型过滤
    base_q = _conversation_type_query(user_id, type).where(
        _has_displayable_assistant_message_query()
    )
    if q.strip():
        text = q.strip()
        metadata_match = select(ConversationDigest.conversation_id).where(
            ConversationDigest.conversation_id == Conversation.id,
            or_(*[column.contains(text, autoescape=True) for column in (
                ConversationDigest.title, ConversationDigest.custom_title,
                ConversationDigest.question, ConversationDigest.summary,
            )]),
        ).exists()
        message_match = select(Message.id).where(
            Message.conversation_id == Conversation.id,
            Message.role.in_(["user", "assistant"]),
            Message.content.contains(text, autoescape=True),
        ).exists()
        base_q = base_q.where(or_(Conversation.title.contains(text, autoescape=True), metadata_match, message_match))

    total = db.scalar(
        select(func.count()).select_from(base_q.subquery())
    ) or 0

    rows: List[Conversation] = db.scalars(
        base_q.order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items: List[ConversationListItem] = []
    digests = {row.conversation_id: row for row in db.scalars(select(ConversationDigest).where(
        ConversationDigest.conversation_id.in_([conv.id for conv in rows])
    )).all()} if rows else {}
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
        first_user = db.scalars(select(Message.content).where(
            Message.conversation_id == conv.id, Message.role == "user",
        ).order_by(Message.id).limit(10)).all()
        fallback_title = next((safe for text in first_user if (safe := _safe_user_message(text))), None)
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
            title=(digests[conv.id].custom_title or digests[conv.id].title or fallback_title or conv.title)[:80]
                if conv.id in digests else (hexagram_summary.question if hexagram_summary else fallback_title or conv.title)[:80],
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            last_user_message=_preview(last_user),
            last_assistant_preview=_preview(last_asst),
            bazi_summary=_four_pillars_summary(conv.bazi_chart_snapshot) if type == "bazi" else None,
            hexagram=hexagram_summary,
            task_context=conv.task_context,
            digest=_digest_response(digests.get(conv.id), db, conv.id),
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
        task_context=conv.task_context,
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

# Metadata endpoints do not mutate Conversation.updated_at.
def _digest_response(digest, db, conversation_id):
    if not digest:
        return DigestResponse()
    latest = db.scalar(select(func.max(Message.id)).where(
        Message.conversation_id == conversation_id,
        Message.role == 'assistant',
    )) or 0
    status = digest.status
    if status == 'pending' and digest.requested_at and digest.requested_at < datetime.utcnow() - timedelta(minutes=2):
        status = 'failed'
    return DigestResponse(
        **{name: getattr(digest, name) for name in (
            'title', 'custom_title', 'topic', 'question', 'summary',
            'source_message_id', 'generated_at',
        )},
        status=status,
        stale=bool(digest.summary and latest > digest.source_message_id),
    )


def _owned_conversation(db, conversation_id, user_id, lock=False):
    query = select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    if lock:
        query = query.with_for_update()
    conv = db.scalar(query)
    if not conv:
        raise HTTPException(status_code=404, detail='会话不存在')
    return conv


@router.get('/{conversation_id}/digest', response_model=DigestResponse)
def get_digest(conversation_id: int, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_or_401)):
    _owned_conversation(db, conversation_id, user_id)
    return _digest_response(db.get(ConversationDigest, conversation_id), db, conversation_id)


class DigestRequest(BaseModel):
    refresh: bool = False


@router.post('/{conversation_id}/digest', response_model=DigestResponse)
def request_digest(conversation_id: int, payload: DigestRequest, background_tasks: BackgroundTasks,
                   db: Session = Depends(get_db), user_id: int = Depends(get_current_user_or_401)):
    # Parent row lock serializes first insert and simultaneous requests.
    _owned_conversation(db, conversation_id, user_id, lock=True)
    digest = db.get(ConversationDigest, conversation_id)
    view = _digest_response(digest, db, conversation_id)
    if view.status == 'pending' or (view.summary and (not payload.refresh or not view.stale)):
        db.commit()
        return view
    now = datetime.utcnow()
    if digest and digest.requested_at and digest.requested_at > now - timedelta(seconds=60):
        raise HTTPException(status_code=429, detail='请稍后再试，原对话仍可继续查看')
    recent = db.scalar(select(func.count()).select_from(ConversationDigest).join(
        Conversation, Conversation.id == ConversationDigest.conversation_id,
    ).where(Conversation.user_id == user_id,
            ConversationDigest.requested_at > now - timedelta(hours=1))) or 0
    if recent >= 10:
        raise HTTPException(status_code=429, detail='本小时整理次数较多，请稍后再试')
    valid_reply = db.scalar(select(Message.id).where(
        Message.conversation_id == conversation_id, Message.role == 'assistant',
        func.length(func.trim(Message.content)) > 0,
    ).limit(1))
    if not valid_reply:
        raise HTTPException(status_code=409, detail='还没有可以整理的解读内容')
    if not digest:
        digest = ConversationDigest(conversation_id=conversation_id)
        db.add(digest)
    digest.status = 'pending'
    digest.request_token = str(uuid4())
    digest.requested_at = now
    db.flush()
    result = _digest_response(digest, db, conversation_id)
    token = digest.request_token
    db.commit()
    background_tasks.add_task(generate_digest, conversation_id, token)
    return result


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


@router.patch('/{conversation_id}/title', response_model=DigestResponse)
def rename_conversation(conversation_id: int, payload: RenameRequest,
                        db: Session = Depends(get_db), user_id: int = Depends(get_current_user_or_401)):
    _owned_conversation(db, conversation_id, user_id, lock=True)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail='请输入标题')
    digest = db.get(ConversationDigest, conversation_id)
    if not digest:
        digest = ConversationDigest(conversation_id=conversation_id)
        db.add(digest)
    digest.custom_title = title
    db.flush()
    result = _digest_response(digest, db, conversation_id)
    db.commit()
    return result
