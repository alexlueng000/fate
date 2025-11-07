from sentence_transformers import SentenceTransformer
m = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
m.save(r"D:\models\all-MiniLM-L6-v2")   # 生成 0_Transformer/ 1_Pooling/ 2_Normalize/
print("OK")