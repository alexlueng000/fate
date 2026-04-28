# app/chat/rag.py
import os
from typing import List, Dict, Any, Tuple, Optional
from functools import lru_cache
from threading import Lock
from kb_rag_mult import load_index, EmbeddingBackend, top_k_cosine


# Global cache for RAG index
_index_cache: Dict[str, Dict[str, Any]] = {}
_index_lock = Lock()


def _load_and_cache_index(index_dir: str) -> Tuple[List[str], List[Dict], Any, Dict[str, Any]]:
    """
    Load index from cache or disk.

    Returns:
        (chunks, sources, embeddings, metadata)
    """
    abs_path = os.path.abspath(index_dir)

    with _index_lock:
        if abs_path in _index_cache:
            return _index_cache[abs_path]

        # Load from disk
        chunks, sources, embs, meta = load_index(index_dir)

        # Pre-fit TFIDF vectorizer if needed
        if meta.get("backend") == "tfidf":
            eb = EmbeddingBackend(force_backend=meta.get("backend", "st"))
            if eb.vectorizer is not None:
                eb.vectorizer.fit(chunks)
            # Cache the fitted vectorizer
            meta["_cached_vectorizer"] = eb.vectorizer

        cached = {
            "chunks": chunks,
            "sources": sources,
            "embs": embs,
            "meta": meta
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
        index_dir = f"kb_index/{kb_type}"

    # 检查索引目录是否存在
    if not os.path.exists(index_dir):
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

    idxs = top_k_cosine(q_vec, embs, k=k)
    passages: List[str] = []
    for i in idxs:
        file_ = sources[i]["file"] if i < len(sources) else "unknown"
        passages.append(f"【{file_}】{chunks[i]}")
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