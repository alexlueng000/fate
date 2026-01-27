"""
敏感词过滤模块
- 从数据库加载敏感词（带内存缓存）
- 支持普通替换和正则替换
- 按优先级和长度排序（长词优先匹配）
"""
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.sensitive_word import SensitiveWord


# 缓存配置
_cache: Optional[list[tuple[str, str, bool]]] = None
_cache_time: Optional[datetime] = None
CACHE_TTL = 300  # 5分钟缓存

# 全局开关：设为 False 可禁用敏感词过滤（用于调试）
FILTER_ENABLED = True


def get_word_mappings(db: Session) -> list[tuple[str, str, bool]]:
    """
    获取敏感词映射（带缓存）
    返回: [(word, replacement, is_regex), ...]
    """
    global _cache, _cache_time
    now = datetime.now()

    if _cache is not None and _cache_time is not None:
        if (now - _cache_time).total_seconds() < CACHE_TTL:
            return _cache

    # 从数据库加载，按优先级和长度排序
    words = db.query(SensitiveWord).filter(
        SensitiveWord.status == 1
    ).order_by(
        SensitiveWord.priority.desc(),
        func.length(SensitiveWord.word).desc()
    ).all()

    _cache = [(w.word, w.replacement, w.is_regex) for w in words]
    _cache_time = now
    return _cache


def apply_content_filters(text: str, db: Session) -> str:
    """
    应用敏感词过滤
    - 按优先级和长度排序（长词优先）
    - 支持普通替换和正则替换
    """
    if not text:
        return text

    # 检查全局开关
    if not FILTER_ENABLED:
        return text

    mappings = get_word_mappings(db)
    for word, replacement, is_regex in mappings:
        if is_regex:
            try:
                text = re.sub(word, replacement, text)
            except re.error:
                # 正则表达式无效，跳过
                pass
        else:
            text = text.replace(word, replacement)
    return text


def clear_cache():
    """清除缓存（管理后台修改后调用）"""
    global _cache, _cache_time
    _cache = None
    _cache_time = None
