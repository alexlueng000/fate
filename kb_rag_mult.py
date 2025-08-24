#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, argparse, numpy as np, glob
from typing import List, Tuple, Dict

# ====== 可选后端：Sentence-Transformers（优先）或 TF-IDF ======
USE_ST = False
try:
    from sentence_transformers import SentenceTransformer
    USE_ST = True
except Exception:
    USE_ST = False

USE_TFIDF = False
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    USE_TFIDF = True
except Exception:
    USE_TFIDF = False

# ====== 文档读取：.txt / .docx（可选 .doc via textract）======
def read_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def read_docx(path: str) -> str:
    try:
        import docx  # python-docx
    except Exception:
        raise RuntimeError("读取 .docx 需要依赖: pip install python-docx")
    doc = docx.Document(path)
    return "\n".join(p.text for p in doc.paragraphs)

def read_doc(path: str) -> str:
    # 可选：如果装了 textract，就能读 .doc；没装就提示转成 .docx
    try:
        import textract
    except Exception:
        raise RuntimeError("读取 .doc 需要 textract（或请先转成 .docx）。安装：pip install textract")
    return textract.process(path).decode("utf-8", "ignore")

def load_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".txt":
        return read_txt(path)
    if ext == ".docx":
        return read_docx(path)
    if ext == ".doc":
        return read_doc(path)
    raise RuntimeError(f"不支持的文件类型: {ext}（支持 .txt / .docx；.doc 需 textract）")

# ====== 切分 ======
def chunk_text(text: str, chunk_size: int = 700, overlap: int = 120) -> List[str]:
    text = text.strip()
    if not text:
        return []
    chunks, i, N = [], 0, len(text)
    while i < N:
        end = min(i + chunk_size, N)
        c = text[i:end].strip()
        if c:
            chunks.append(c)
        if end == N:
            break
        i = end - overlap if end - overlap > i else end
    return chunks

# ====== 向量后端（固定：索引用哪个，查询也用哪个）======
class EmbeddingBackend:
    def __init__(self, force_backend: str | None = None):
        self.backend = None
        self.vectorizer = None
        if force_backend == "st":
            from sentence_transformers import SentenceTransformer
            self.backend = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            return
        if force_backend == "tfidf":
            from sklearn.feature_extraction.text import TfidfVectorizer
            self.vectorizer = TfidfVectorizer(max_features=50000)
            return
        # 自动选择
        if USE_ST:
            self.backend = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        elif USE_TFIDF:
            self.vectorizer = TfidfVectorizer(max_features=50000)
        else:
            raise RuntimeError("缺少可用的向量化后端：pip install sentence-transformers 或 scikit-learn")

    def fit_transform(self, texts: List[str]) -> np.ndarray:
        if self.backend is not None:
            embs = self.backend.encode(texts, normalize_embeddings=True)
            return np.asarray(embs, dtype=np.float32)
        X = self.vectorizer.fit_transform(texts)
        # L2 normalize
        norms = np.sqrt((X.power(2)).sum(axis=1)).A1 + 1e-12
        X = X.multiply(1.0 / norms[:, None])
        return np.asarray(X.todense(), dtype=np.float32)

    def transform(self, texts: List[str]) -> np.ndarray:
        if self.backend is not None:
            embs = self.backend.encode(texts, normalize_embeddings=True)
            return np.asarray(embs, dtype=np.float32)
        X = self.vectorizer.transform(texts)
        norms = np.sqrt((X.power(2)).sum(axis=1)).A1 + 1e-12
        X = X.multiply(1.0 / norms[:, None])
        return np.asarray(X.todense(), dtype=np.float32)

# ====== 索引保存/读取 ======
def save_index(index_dir: str, chunks: List[str], embs: np.ndarray, meta: dict, sources: List[Dict]):
    os.makedirs(index_dir, exist_ok=True)
    with open(os.path.join(index_dir, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump({"chunks": chunks, "sources": sources}, f, ensure_ascii=False)
    np.savez_compressed(
        os.path.join(index_dir, "embeddings.npz"),
        embeddings=embs.astype(np.float32),
        meta=np.bytes_(json.dumps(meta, ensure_ascii=False)),
    )

def load_index(index_dir: str):
    chunks_path = os.path.join(index_dir, "chunks.json")
    embs_path = os.path.join(index_dir, "embeddings.npz")
    if not (os.path.exists(chunks_path) and os.path.exists(embs_path)):
        raise FileNotFoundError(f"索引缺失：{chunks_path} 或 {embs_path}")
    with open(chunks_path, "r", encoding="utf-8") as f:
        j = json.load(f)
    chunks, sources = j["chunks"], j["sources"]
    data = np.load(embs_path)
    embs = data["embeddings"]
    meta = json.loads(str(data["meta"].tobytes(), "utf-8"))
    return chunks, sources, embs, meta

# ====== 相似度检索 ======
def top_k_cosine(q_vec: np.ndarray, db_vecs: np.ndarray, k: int = 3) -> List[int]:
    sims = (db_vecs @ q_vec.squeeze().astype(np.float32))
    return np.argsort(-sims)[:k].tolist()

# ====== ingest 命令 ======
def gather_files(inputs: List[str], use_glob: bool) -> List[str]:
    paths: List[str] = []
    for inp in inputs:
        if os.path.isdir(inp):
            for ext in ("*.txt", "*.docx", "*.doc"):
                paths.extend(glob.glob(os.path.join(inp, ext)))
        else:
            if use_glob and any(ch in inp for ch in ["*", "?", "["]):
                paths.extend(glob.glob(inp))
            else:
                paths.append(inp)
    # 去重 & 存在性检查
    uniq = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.exists(p) and p not in uniq:
            uniq.append(p)
    return uniq

def cmd_ingest(args):
    files = gather_files(args.input, use_glob=args.glob)
    if not files:
        print("❌ 未发现可用文件。支持 .txt / .docx（.doc 需 textract）")
        return

    all_chunks: List[str] = []
    all_sources: List[Dict] = []
    for path in files:
        try:
            text = load_file(path)
        except Exception as e:
            print(f"跳过不可读取文件: {path} | 原因: {e}")
            continue
        chunks = chunk_text(text, chunk_size=args.chunk_size, overlap=args.overlap)
        for c in chunks:
            all_sources.append({"file": os.path.basename(path)})
        all_chunks.extend(chunks)

    if not all_chunks:
        print("❌ 文件为空或切分后无内容")
        return

    # 选择并固化后端
    backend_tag = "st" if USE_ST else ("tfidf" if USE_TFIDF else "none")
    eb = EmbeddingBackend(force_backend=backend_tag)
    embs = eb.fit_transform(all_chunks)

    meta = {
        "backend": backend_tag,  # 'st' / 'tfidf'
        "model": "all-MiniLM-L6-v2" if backend_tag == "st" else "tfidf",
        "chunk_size": args.chunk_size,
        "overlap": args.overlap,
        "num_chunks": len(all_chunks),
        "num_files": len(files),
        "files": [os.path.basename(p) for p in files],
    }
    save_index(args.index_dir, all_chunks, embs, meta, all_sources)
    print(f"✅ 索引完成：{args.index_dir}")
    print(f"- 文件数: {meta['num_files']} -> {', '.join(meta['files'])}")
    print(f"- 分片数: {meta['num_chunks']}")
    print(f"- 向量维度: {embs.shape[1]}")
    print(f"- 后端: {meta['backend']} ({meta['model']})")

# ====== query 命令 ======
def cmd_query(args):
    chunks, sources, embs, meta = load_index(args.index_dir)
    backend_tag = meta.get("backend", "st")
    eb = EmbeddingBackend(force_backend=backend_tag)
    # TF-IDF 需要用语料拟合词表
    if backend_tag == "tfidf" and eb.vectorizer is not None:
        eb.vectorizer.fit(chunks)

    q_emb = eb.transform([args.q])
    q_emb = q_emb / (np.linalg.norm(q_emb, axis=1, keepdims=True) + 1e-12)

    idxs = top_k_cosine(q_emb, embs, k=args.k)
    print(f"🔎 Top-{args.k} 结果：\n")
    for rank, i in enumerate(idxs, 1):
        src = sources[i]["file"] if i < len(sources) else "unknown"
        preview = chunks[i][:400].replace("\n", " ")
        if len(chunks[i]) > 400: preview += "..."
        print(f"[{rank}] 片段ID={i} | 来自: {src}")
        print(preview)
        print("-" * 80)

# ====== CLI ======
def build_cli():
    p = argparse.ArgumentParser(description="多文件本地RAG：读取 .txt / .docx（可选 .doc），切分、向量化、检索")
    sub = p.add_subparsers(dest="cmd")

    pi = sub.add_parser("ingest", help="构建索引（支持多文件/目录/通配符）")
    pi.add_argument("-i", "--input", nargs="+", required=True,
                    help="文件/目录/通配符，多项用空格分隔。例如：-i a.txt b.docx ./docs '*.txt'")
    pi.add_argument("-o", "--index-dir", default="./kb_index", help="索引输出目录")
    pi.add_argument("--chunk-size", type=int, default=700, help="分片字符数")
    pi.add_argument("--overlap", type=int, default=120, help="分片重叠字符数")
    pi.add_argument("--glob", action="store_true", help="把 -i 参数按通配符展开")
    pi.set_defaults(func=cmd_ingest)

    pq = sub.add_parser("query", help="查询索引")
    pq.add_argument("-o", "--index-dir", default="./kb_index", help="索引目录")
    pq.add_argument("-q", required=True, help="查询问题")
    pq.add_argument("-k", type=int, default=3, help="返回片段数 Top-k")
    pq.set_defaults(func=cmd_query)

    return p

def main():
    parser = build_cli()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help(); return
    args.func(args)

if __name__ == "__main__":
    main()
