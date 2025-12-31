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


def retrieve_kb(query: str, index_dir: str, k: int = 3) -> List[str]:
    """从本地知识库取 Top-k 片段，返回带文件名的片段文本列表"""
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