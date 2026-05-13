# 数据库迁移 SQL

## 方法1：使用 init_db.py（推荐）

```bash
# 在线上服务器执行
cd ~/fate
source venv311/bin/activate
python init_db.py
```

这会自动创建 `api_call_logs` 表（如果不存在）或添加新字段（如果表已存在但缺少字段）。

## 方法2：手动执行 SQL

如果 `api_call_logs` 表已存在，只需添加新字段：

```sql
-- 添加 prompt_cache_hit_tokens 字段
ALTER TABLE api_call_logs 
ADD COLUMN prompt_cache_hit_tokens INT NOT NULL DEFAULT 0 COMMENT '缓存命中 token (0.1元/百万)' 
AFTER completion_tokens;

-- 添加 prompt_cache_miss_tokens 字段
ALTER TABLE api_call_logs 
ADD COLUMN prompt_cache_miss_tokens INT NOT NULL DEFAULT 0 COMMENT '缓存未命中 token (1元/百万)' 
AFTER prompt_cache_hit_tokens;
```

如果 `api_call_logs` 表不存在，直接运行 `python init_db.py` 会自动创建完整的表。

---

## 缓存统计查询

### 查看最近 24 小时的缓存命中率

```sql
SELECT 
    SUM(prompt_cache_hit_tokens) as cache_hits,
    SUM(prompt_cache_miss_tokens) as cache_miss,
    ROUND(SUM(prompt_cache_hit_tokens) / (SUM(prompt_cache_hit_tokens) + SUM(prompt_cache_miss_tokens)) * 100, 2) as hit_rate_percent
FROM api_call_logs 
WHERE created_at > DATE_SUB(NOW(), INTERVAL 1 DAY);
```

### 查看每个模型的缓存效果

```sql
SELECT 
    model,
    COUNT(*) as call_count,
    SUM(prompt_cache_hit_tokens) as cache_hits,
    SUM(prompt_cache_miss_tokens) as cache_miss,
    ROUND(SUM(prompt_cache_hit_tokens) / (SUM(prompt_cache_hit_tokens) + SUM(prompt_cache_miss_tokens)) * 100, 2) as hit_rate_percent
FROM api_call_logs 
WHERE created_at > DATE_SUB(NOW(), INTERVAL 1 DAY)
GROUP BY model;
```

### 估算缓存节省的费用

```sql
SELECT 
    -- 缓存命中节省的费用（原本 1元/百万，现在 0.1元/百万，节省 0.9元/百万）
    ROUND(SUM(prompt_cache_hit_tokens) / 1000000 * 0.9, 2) as saved_yuan,
    -- 实际缓存费用
    ROUND(SUM(prompt_cache_hit_tokens) / 1000000 * 0.1, 2) as cache_cost_yuan,
    -- 未命中的正常费用
    ROUND(SUM(prompt_cache_miss_tokens) / 1000000 * 1.0, 2) as normal_cost_yuan
FROM api_call_logs 
WHERE created_at > DATE_SUB(NOW(), INTERVAL 1 DAY);
```
