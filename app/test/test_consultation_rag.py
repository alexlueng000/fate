from pathlib import Path
import numpy as np
from app.chat import rag
from kb_rag_mult import EmbeddingBackend, save_index


def test_type_specific_paths_and_environment_override(monkeypatch, tmp_path):
    monkeypatch.setenv("KB_BAZI_INDEX_DIR", str(tmp_path / "bazi"))
    monkeypatch.setenv("KB_LIUYAO_INDEX_DIR", str(tmp_path / "liuyao"))
    assert rag.resolve_index_dir("bazi") != rag.resolve_index_dir("liuyao")
    assert rag.retrieve_kb("问题", kb_type="bazi") == []


def test_saved_vectorizer_sources_and_zero_similarity(tmp_path):
    chunks = ["career opportunity planning", "relationship communication"]
    embed = EmbeddingBackend(force_backend="tfidf")
    vectors = embed.fit_transform(chunks)
    save_index(str(tmp_path), chunks, vectors, {"backend": "tfidf"}, [{"file": "career.txt"}, {"file": "relationship.txt"}], embed.vectorizer)
    rag.clear_index_cache()
    passages = rag.retrieve_kb("career planning", str(tmp_path), k=3)
    assert len(passages) == 1
    assert "career.txt · " in passages[0]
    assert rag.retrieve_kb("unrelatedunknownword", str(tmp_path)) == []
    assert rag.retrieve_kb("career", str(tmp_path), k=0) == []


def test_rebuild_invalidates_index_cache(tmp_path):
    chunks = ["career planning"]
    embed = EmbeddingBackend(force_backend="tfidf")
    vectors = embed.fit_transform(chunks)
    save_index(str(tmp_path), chunks, vectors, {"backend": "tfidf"}, [{"file": "old.txt"}], embed.vectorizer)
    assert "old.txt" in rag.retrieve_kb("career", str(tmp_path))[0]
    save_index(str(tmp_path), chunks, vectors, {"backend": "tfidf"}, [{"file": "new.txt"}], embed.vectorizer)
    assert "new.txt" in rag.retrieve_kb("career", str(tmp_path))[0]


def test_chinese_retrieval_without_whitespace(monkeypatch, tmp_path):
    monkeypatch.setenv('KB_TFIDF_ANALYZER', 'char')
    chunks = ['官杀与事业方向相关，应结合全局分析。', '婚姻关系需要沟通和观察。']
    embed = EmbeddingBackend(force_backend='tfidf')
    vectors = embed.fit_transform(chunks)
    save_index(str(tmp_path), chunks, vectors, {'backend': 'tfidf'}, [{'file': 'career.txt'}, {'file': 'relationship.txt'}], embed.vectorizer)
    matches = rag.retrieve_kb('事业方向', str(tmp_path))
    assert len(matches) == 1 and 'career.txt' in matches[0]
    assert rag.retrieve_kb('火星旅行', str(tmp_path)) == []
