from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.chat import utils
from app.chat.deepseek_client import DeepSeekEmptyResponseError, call_deepseek, call_deepseek_stream, set_caller
from app.chat.markdown_utils import normalize_markdown
from app.chat.rag import retrieve_kb
from app.chat.sse import sse_pack, sse_response
from app.db import SessionLocal, get_db
from app.liuyao.chat_service import _fallback_non_stream_reply, _post_process
from app.liuyao.paipan import LiuyaoPaipan
from app.liuyao.prompts import build_opening_user_message, build_system_prompt
from app.models.guest_liuyao import GuestLiuyao
from app.models.liuyao import LiuyaoHexagram
from app.routers.liuyao import HexagramDetailResponse, PaipanRequest


router = APIRouter(prefix="/guest/liuyao", tags=["guest-liuyao"])

GUEST_LIUYAO_PROMPT_VERSION = "guest_liuyao_first_reading_v1"
GUEST_LIUYAO_TTL_DAYS = 7
GUEST_LIUYAO_SESSION_LIMIT_HOURS = 24


class GuestLiuyaoStartRequest(PaipanRequest):
    guest_session_id: str


def _client_ip(request: Request) -> Optional[str]:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()[:45]
    if request.client:
        return request.client.host[:45]
    return None


def _ensure_guest_quota(db: Session, guest_session_id: str) -> None:
    cutoff = datetime.utcnow() - timedelta(hours=GUEST_LIUYAO_SESSION_LIMIT_HOURS)
    existing = (
        db.query(GuestLiuyao)
        .filter(
            GuestLiuyao.guest_session_id == guest_session_id,
            GuestLiuyao.created_at >= cutoff,
            GuestLiuyao.status.in_(["running", "succeeded"]),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="游客每天只能免费解卦一次，登录后可继续追问或获得更多次数",
        )


def _build_transient_hexagram(data: GuestLiuyaoStartRequest, timestamp: datetime, result: dict) -> LiuyaoHexagram:
    return LiuyaoHexagram(
        id=0,
        user_id=0,
        hexagram_id=result["hexagram_id"],
        question=data.question,
        gender=data.gender,
        method=data.method,
        numbers={"numbers": data.numbers} if data.numbers else None,
        timestamp=timestamp,
        location=data.location,
        solar_time=data.solar_time,
        main_gua=result.get("main_gua"),
        change_gua=result.get("change_gua"),
        gua_type=None,
        shi_yao=result.get("shi_yao"),
        ying_yao=result.get("ying_yao"),
        lines={"lines": result.get("lines", [])},
        change_lines={"lines": result.get("change_lines", [])},
        ganzhi=result.get("ganzhi"),
        jiqi=result.get("jieqi"),
        shensha=result.get("shensha"),
        gua_shen=result.get("gua_shen"),
        lunar_date=result.get("lunar_date"),
        created_at=datetime.utcnow(),
    )


def _hexagram_payload(hexagram: LiuyaoHexagram) -> dict:
    return HexagramDetailResponse.model_validate(hexagram).model_dump(mode="json")


@router.post("/paipan", response_model=HexagramDetailResponse)
def create_guest_liuyao_paipan(
    data: GuestLiuyaoStartRequest,
):
    guest_session_id = data.guest_session_id.strip()
    if len(guest_session_id) < 8 or len(guest_session_id) > 64:
        raise HTTPException(status_code=400, detail="guest_session_id 无效")

    if data.method not in ["number", "coin", "time"]:
        raise HTTPException(status_code=400, detail="起卦方式必须是 number/coin/time")
    if data.method == "number" and (not data.numbers or len(data.numbers) != 3):
        raise HTTPException(status_code=400, detail="数字起卦需要提供3个数字")

    timestamp = datetime.fromisoformat(data.timestamp) if data.timestamp else datetime.now()

    try:
        paipan = LiuyaoPaipan(
            question=data.question,
            method=data.method,
            gender=data.gender,
            timestamp=timestamp,
            location=data.location,
            solar_time=data.solar_time,
            numbers=data.numbers,
        )
        paipan_result = paipan.calc()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"排盘失败: {str(exc)}")

    transient_hexagram = _build_transient_hexagram(data, timestamp, paipan_result)
    return _hexagram_payload(transient_hexagram)


@router.post("/start")
def start_guest_liuyao(
    data: GuestLiuyaoStartRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    guest_session_id = data.guest_session_id.strip()
    if len(guest_session_id) < 8 or len(guest_session_id) > 64:
        raise HTTPException(status_code=400, detail="guest_session_id 无效")

    _ensure_guest_quota(db, guest_session_id)

    if data.method not in ["number", "coin", "time"]:
        raise HTTPException(status_code=400, detail="起卦方式必须是 number/coin/time")
    if data.method == "number" and (not data.numbers or len(data.numbers) != 3):
        raise HTTPException(status_code=400, detail="数字起卦需要提供3个数字")

    timestamp = datetime.fromisoformat(data.timestamp) if data.timestamp else datetime.now()

    try:
        paipan = LiuyaoPaipan(
            question=data.question,
            method=data.method,
            gender=data.gender,
            timestamp=timestamp,
            location=data.location,
            solar_time=data.solar_time,
            numbers=data.numbers,
        )
        paipan_result = paipan.calc()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"排盘失败: {str(exc)}")

    transient_hexagram = _build_transient_hexagram(data, timestamp, paipan_result)
    hexagram_data = _hexagram_payload(transient_hexagram)

    now = datetime.utcnow()
    record = GuestLiuyao(
        public_id=str(uuid.uuid4()),
        guest_session_id=guest_session_id,
        status="running",
        question=data.question,
        gender=data.gender,
        method=data.method,
        numbers={"numbers": data.numbers} if data.numbers else None,
        timestamp=timestamp,
        location=data.location,
        solar_time=data.solar_time,
        hexagram_result=hexagram_data,
        prompt_version=GUEST_LIUYAO_PROMPT_VERSION,
        request_ip=_client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
        expires_at=now + timedelta(days=GUEST_LIUYAO_TTL_DAYS),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    kb_query = " ".join(filter(None, [
        transient_hexagram.main_gua,
        transient_hexagram.change_gua,
        transient_hexagram.question,
    ]))
    try:
        kb_passages = retrieve_kb(query=kb_query, kb_type="liuyao", k=5)
    except Exception:
        kb_passages = []

    base_prompt = utils.load_liuyao_system_prompt_from_db()
    system_prompt = build_system_prompt(transient_hexagram, kb_passages, base_prompt=base_prompt)
    opening_user_msg = build_opening_user_message(transient_hexagram)
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": opening_user_msg}]

    def gen():
        final = ""
        try:
            yield sse_pack(json.dumps(
                {
                    "meta": {
                        "public_id": record.public_id,
                        "hexagram": hexagram_data,
                        "guest": True,
                    }
                },
                ensure_ascii=False,
            ))
            normalizer = utils.IncrementalNormalizer(normalize_interval=50)
            set_caller("guest_liuyao_start")
            try:
                for delta in call_deepseek_stream(messages, thinking=False):
                    if not delta:
                        continue
                    clean = normalizer.append(delta)
                    if clean:
                        yield sse_pack(json.dumps({"text": clean, "replace": True}, ensure_ascii=False))
                final = normalizer.finalize()
            except DeepSeekEmptyResponseError:
                final = _fallback_non_stream_reply(messages, "guest_liuyao_start")

            if not final.strip():
                final = _post_process(call_deepseek(messages, thinking=False))
            final = normalize_markdown(final).strip()
            if final:
                yield sse_pack(json.dumps({"text": final, "replace": True}, ensure_ascii=False))
            yield sse_pack("[DONE]")
        except Exception as exc:
            with SessionLocal() as new_db:
                row = new_db.query(GuestLiuyao).filter(GuestLiuyao.public_id == record.public_id).first()
                if row:
                    row.status = "failed"
                    row.error_message = str(exc)[:1000]
                    new_db.commit()
            yield sse_pack(json.dumps(
                {"text": "抱歉，AI 服务暂时不可用，请稍后再试。", "replace": True},
                ensure_ascii=False,
            ))
            yield sse_pack("[DONE]")
        finally:
            if final.strip():
                with SessionLocal() as new_db:
                    row = new_db.query(GuestLiuyao).filter(GuestLiuyao.public_id == record.public_id).first()
                    if row:
                        row.status = "succeeded"
                        row.analysis_markdown = final
                        row.error_message = None
                        new_db.commit()

    return sse_response(gen)
