"""
敏感词服务层
"""
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.sensitive_word import SensitiveWord


def get_by_id(db: Session, word_id: int) -> Optional[SensitiveWord]:
    """根据ID获取敏感词"""
    return db.query(SensitiveWord).filter(SensitiveWord.id == word_id).first()


def get_by_word(db: Session, word: str) -> Optional[SensitiveWord]:
    """根据敏感词获取"""
    return db.query(SensitiveWord).filter(SensitiveWord.word == word).first()


def list_words(
    db: Session,
    status: Optional[int] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[SensitiveWord]:
    """列表查询敏感词"""
    query = db.query(SensitiveWord)

    if status is not None:
        query = query.filter(SensitiveWord.status == status)

    if category:
        query = query.filter(SensitiveWord.category == category)

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (SensitiveWord.word.like(search_pattern)) |
            (SensitiveWord.replacement.like(search_pattern))
        )

    query = query.order_by(
        SensitiveWord.priority.desc(),
        SensitiveWord.id.desc()
    )

    return query.offset(offset).limit(limit).all()


def count_words(
    db: Session,
    status: Optional[int] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
) -> int:
    """统计敏感词数量"""
    query = db.query(func.count(SensitiveWord.id))

    if status is not None:
        query = query.filter(SensitiveWord.status == status)

    if category:
        query = query.filter(SensitiveWord.category == category)

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (SensitiveWord.word.like(search_pattern)) |
            (SensitiveWord.replacement.like(search_pattern))
        )

    return query.scalar() or 0


def get_all_active_words(db: Session) -> list[SensitiveWord]:
    """获取所有启用的敏感词（按优先级和长度排序）"""
    return db.query(SensitiveWord).filter(
        SensitiveWord.status == 1
    ).order_by(
        SensitiveWord.priority.desc(),
        func.length(SensitiveWord.word).desc()
    ).all()


def create_word(
    db: Session,
    word: str,
    replacement: str,
    category: str = "general",
    is_regex: bool = False,
    priority: int = 0,
    note: Optional[str] = None,
) -> SensitiveWord:
    """创建敏感词"""
    sensitive_word = SensitiveWord(
        word=word,
        replacement=replacement,
        category=category,
        is_regex=is_regex,
        priority=priority,
        note=note,
        status=1,
    )
    db.add(sensitive_word)
    db.commit()
    db.refresh(sensitive_word)
    return sensitive_word


def update_word(
    db: Session,
    word_id: int,
    word: Optional[str] = None,
    replacement: Optional[str] = None,
    category: Optional[str] = None,
    is_regex: Optional[bool] = None,
    priority: Optional[int] = None,
    note: Optional[str] = None,
) -> Optional[SensitiveWord]:
    """更新敏感词"""
    sensitive_word = get_by_id(db, word_id)
    if not sensitive_word:
        return None

    if word is not None:
        sensitive_word.word = word
    if replacement is not None:
        sensitive_word.replacement = replacement
    if category is not None:
        sensitive_word.category = category
    if is_regex is not None:
        sensitive_word.is_regex = is_regex
    if priority is not None:
        sensitive_word.priority = priority
    if note is not None:
        sensitive_word.note = note

    db.commit()
    db.refresh(sensitive_word)
    return sensitive_word


def enable_word(db: Session, word_id: int) -> Optional[SensitiveWord]:
    """启用敏感词"""
    sensitive_word = get_by_id(db, word_id)
    if not sensitive_word:
        return None

    sensitive_word.status = 1
    db.commit()
    db.refresh(sensitive_word)
    return sensitive_word


def disable_word(db: Session, word_id: int) -> Optional[SensitiveWord]:
    """禁用敏感词"""
    sensitive_word = get_by_id(db, word_id)
    if not sensitive_word:
        return None

    sensitive_word.status = 0
    db.commit()
    db.refresh(sensitive_word)
    return sensitive_word


def delete_word(db: Session, word_id: int) -> bool:
    """删除敏感词"""
    sensitive_word = get_by_id(db, word_id)
    if not sensitive_word:
        return False

    db.delete(sensitive_word)
    db.commit()
    return True


def batch_create_words(
    db: Session,
    words: list[dict],
) -> list[SensitiveWord]:
    """批量创建敏感词"""
    created = []
    for item in words:
        # 跳过已存在的
        if get_by_word(db, item["word"]):
            continue

        sensitive_word = SensitiveWord(
            word=item["word"],
            replacement=item["replacement"],
            category=item.get("category", "general"),
            is_regex=item.get("is_regex", False),
            priority=item.get("priority", 0),
            note=item.get("note"),
            status=1,
        )
        db.add(sensitive_word)
        created.append(sensitive_word)

    if created:
        db.commit()
        for w in created:
            db.refresh(w)

    return created
