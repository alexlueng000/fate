# app/routers/kb_router.py
from fastapi import APIRouter, UploadFile, File, Depends
from pydantic import BaseModel
from typing import Optional

from app.services import kb

router = APIRouter(prefix="/kb", tags=["KnowledgeBase"])

class ReindexReq(BaseModel):
    mode: str = "auto"
    backend: Optional[str] = None
    chunk_size: int = 700
    overlap: int = 120

class QueryReq(BaseModel):
    q: str
    k: int = 5

@router.get("/files")
def list_files():
    return {"files": kb.list_files()}

@router.post("/files/upload")
def upload_file(f: UploadFile = File(...)):
    return kb.save_file(f, f.filename)

@router.delete("/files/{filename}")
def delete_file(filename: str):
    kb.delete_file(filename)
    return {"ok": True}

@router.get("/index/meta")
def index_meta():
    return {"meta": kb.get_index_meta()}

@router.post("/reindex")
def reindex(req: ReindexReq):
    return {"meta": kb.rebuild_index(**req.model_dump())}

@router.post("/query")
def query(req: QueryReq):
    return {"results": kb.query_kb(req.q, req.k)}
