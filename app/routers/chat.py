from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db import get_db
# from ..security import get_current_user
from ..schemas import ChatRequest, ChatResponse
from ..services.ai import call_ai

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, db: Session = Depends(get_db)):
    reply = await call_ai(req.messages)
    return ChatResponse(reply=reply)
