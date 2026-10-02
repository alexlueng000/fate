# app/chat/rag.py
import os
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from threading import Lock
from kb_rag_mult import load_index, EmbeddingBackend, top_k_cosine, TFIDF_MODEL_FILENAME


# Global cache for RAG index
_index_cache: Dict[str, Dict[str, Any]] = {}
_index_lock = Lock()


def resolve_index_dir(kb_type: str = "bazi") -> str:
    if kb_type not in ("bazi", "liuyao"):
        raise ValueError("Unknown knowledge base type")
    root = Path(__file__).resolve().parents[2]
    override = os.getenv(f"KB_{kb_type.upper()}_INDEX_DIR")
    if override:
        return str(Path(override).resolve())
    canonical = root / "kb_index" / kb_type
    legacy = root / ("kb_index_bazi" if kb_type == "bazi" else "kb_index_liuyao")
    return str(canonical if (canonical / "chunks.json").is_file() or not (legacy / "chunks.json").is_file() else legacy)


def _load_and_cache_index(index_dir: str) -> Dict[str, Any]:
    """
    Load index from cache or disk.

    Returns:
        Dictionary containing chunks, sources, embeddings, metadata and signature.
    """
    abs_path = os.path.abspath(index_dir)

    with _index_lock:
        signature = tuple((Path(abs_path) / name).stat().st_mtime_ns for name in ("chunks.json", "embeddings.npz"))
        if abs_path in _index_cache and _index_cache[abs_path].get("signature") == signature:
            return _index_cache[abs_path]

        # Load from disk
        chunks, sources, embs, meta = load_index(index_dir)

        # Pre-fit TFIDF vectorizer if needed
        if meta.get("backend") == "tfidf":
            model_path = os.path.join(abs_path, TFIDF_MODEL_FILENAME)
            eb = EmbeddingBackend(force_backend="tfidf", tfidf_model_path=model_path)
            if eb.vectorizer is not None and not os.path.isfile(model_path):
                eb.vectorizer.fit(chunks)
            # Cache the fitted vectorizer
            meta["_cached_vectorizer"] = eb.vectorizer

        cached = {
            "chunks": chunks,
            "sources": sources,
            "embs": embs,
            "meta": meta,
            "signature": signature,
        }
        _index_cache[abs_path] = cached

        return cached


def retrieve_kb(query: str, index_dir: str = None, kb_type: str = "bazi", k: int = 3) -> List[str]:
    """
    从本地知识库取 Top-k 片段，返回带文件名的片段文本列表

    Args:
        query: 查询文本
        index_dir: 索引目录（优先使用，如果指定则忽略 kb_type）
        kb_type: 知识库类型 "bazi" | "liuyao"，默认 "bazi"
        k: 返回片段数量

    Returns:
        带文件名的片段文本列表
    """
    # 如果没有指定 index_dir，根据 kb_type 自动构建
    if index_dir is None:
        index_dir = resolve_index_dir(kb_type)

    # 检查索引目录是否存在
    if not os.path.isfile(os.path.join(index_dir, "chunks.json")):
        from app.core.logging import get_logger
        logger = get_logger("rag")
        logger.warning(f"Knowledge base index not found: {index_dir}")
        return []

    cached = _load_and_cache_index(index_dir)
    chunks = cached["chunks"]
    sources = cached["sources"]
    embs = cached["embs"]
    meta = cached["meta"]

    # Use cached vectorizer if available
    if "_cached_vectorizer" in meta:
        eb = EmbeddingBackend(force_backend=meta.get("backend", "st"))
        eb.vectorizer = meta["_cached_vectorizer"]
        q_vec = eb.transform([query])
    else:
        eb = EmbeddingBackend(force_backend=meta.get("backend", "st"))
        q_vec = eb.transform([query])

    if k <= 0 or not chunks:
        return []
    idxs = top_k_cosine(q_vec, embs, k=min(k, len(chunks)))
    passages: List[str] = []
    for i in idxs:
        score = float(embs[i] @ q_vec.squeeze())
        if score <= 0:
            continue
        file_ = sources[i]["file"] if i < len(sources) else "unknown"
        source_id = hashlib.sha256(chunks[i].encode("utf-8")).hexdigest()[:12]
        passages.append(f"【{file_} · {source_id}】{chunks[i]}")
    from app.core.logging import get_logger
    get_logger("rag").info("retrieval_completed", kb_type=kb_type, count=len(passages), index=os.path.basename(index_dir))
    return passages


def clear_index_cache(index_dir: Optional[str] = None) -> None:
    """
    Clear cached index.

    Args:
        index_dir: If specified, only clear this index; otherwise clear all.
    """
    with _index_lock:
        if index_dir:
            abs_path = os.path.abspath(index_dir)
            _index_cache.pop(abs_path, None)
        else:
            _index_cache.clear()
