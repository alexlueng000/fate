# app/services/kb_service.py
import os, json, shutil, hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import HTTPException

from kb_rag_mult import chunk_text, EmbeddingBackend, save_index, load_index

KB_FILES_DIR = os.getenv("KB_FILES_DIR", "./kb_files")
KB_INDEX_DIR = os.getenv("KB_INDEX_DIR", "./kb_index")
CHUNKS_JSON = os.path.join(KB_INDEX_DIR, "chunks.json")
EMB_NPZ     = os.path.join(KB_INDEX_DIR, "embeddings.npz")
MANIFEST    = os.path.join(KB_INDEX_DIR, "manifest.json")
ALLOWED_EXT = {".txt", ".docx", ".doc"}

os.makedirs(KB_FILES_DIR, exist_ok=True)
os.makedirs(KB_INDEX_DIR, exist_ok=True)

# ----------- 工具函数 -----------
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1024*1024), b""):
            h.update(ch)
    return h.hexdigest()

def list_files() -> List[Dict[str, Any]]:
    """列出知识库文件"""
    items = []
    for name in os.listdir(KB_FILES_DIR):
        path = os.path.join(KB_FILES_DIR, name)
        if not os.path.isfile(path): 
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in ALLOWED_EXT: 
            continue
        st = os.stat(path)
        items.append({
            "filename": name,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            "md5": _md5_file(path)
        })
    return sorted(items, key=lambda x: x["filename"])

def save_file(upload_file, filename: str) -> Dict[str, Any]:
    """保存上传文件"""
    dest = os.path.join(KB_FILES_DIR, filename)
    with open(dest, "wb") as out:
        shutil.copyfileobj(upload_file.file, out)
    st = os.stat(dest)
    return {"filename": filename, "size": st.st_size, "mtime": int(st.st_mtime), "md5": _md5_file(dest)}

def delete_file(filename: str):
    """删除文件"""
    path = os.path.join(KB_FILES_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, "文件不存在")
    os.remove(path)

def get_index_meta():
    """查看索引 meta"""
    if not (os.path.exists(CHUNKS_JSON) and os.path.exists(EMB_NPZ)):
        raise HTTPException(404, "索引不存在，请先重建")
    _, _, _, meta = load_index(KB_INDEX_DIR)
    return meta

def rebuild_index(mode: str = "auto", backend: Optional[str] = None, chunk_size: int = 700, overlap: int = 120):
    """
    重建索引
    mode = "full" 全量
    mode = "auto" 增量
    """
    files = list_files()
    if not files:
        raise HTTPException(400, "知识库目录为空")

    # 简化：这里先直接全量构建
    eb = EmbeddingBackend(force_backend=backend or "st")

    all_chunks, all_sources, all_embs = [], [], None
    import numpy as np
    for f in files:
        path = os.path.join(KB_FILES_DIR, f["filename"])
        text = open(path, "r", encoding="utf-8", errors="ignore").read() if path.endswith(".txt") else None
        if not text:
            continue
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        embs = eb.transform(chunks)
        all_chunks.extend(chunks)
        all_sources.extend([{"file": f["filename"]} for _ in chunks])
        all_embs = embs if all_embs is None else np.vstack([all_embs, embs])

    meta = {
        "backend": backend or "st",
        "chunk_size": chunk_size,
        "overlap": overlap,
        "num_chunks": len(all_chunks),
        "num_files": len(files),
        "files": [f["filename"] for f in files],
        "last_build": _now(),
    }
    save_index(KB_INDEX_DIR, all_chunks, all_embs, meta, all_sources)
    return meta

def query_kb(q: str, k: int = 5):
    """检索"""
    if not (os.path.exists(CHUNKS_JSON) and os.path.exists(EMB_NPZ)):
        raise HTTPException(404, "索引不存在，请先重建")
    chunks, sources, embs, meta = load_index(KB_INDEX_DIR)
    eb = EmbeddingBackend(force_backend=meta.get("backend", "st"))
    if meta.get("backend") == "tfidf" and eb.vectorizer is not None:
        eb.vectorizer.fit(chunks)
    q_vec = eb.transform([q])
    import numpy as np
    sims = embs @ q_vec.squeeze().astype("float32")
    idxs = np.argsort(-sims)[:k].tolist()
    return [{"file": sources[i]["file"], "score": float(sims[i]), "text": chunks[i][:200]} for i in idxs]
