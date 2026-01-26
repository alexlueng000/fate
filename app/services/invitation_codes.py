# app/services/invitation_codes.py
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.invitation_code import InvitationCode, InvitationCodeUsage


def generate_code(length: int = 8) -> str:
    """
    生成随机邀请码
    - 使用大写字母和数字
    - 移除容易混淆的字符: 0, O, I, 1
    """
    alphabet = string.ascii_uppercase + string.digits
    # 移除容易混淆的字符
    alphabet = alphabet.replace('0', '').replace('O', '').replace('I', '').replace('1', '')
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def get_by_id(db: Session, code_id: int) -> Optional[InvitationCode]:
    """按ID获取邀请码"""
    return db.get(InvitationCode, code_id)


def get_by_code(db: Session, code: str) -> Optional[InvitationCode]:
    """按邀请码字符串获取"""
    if not code:
        return None
    stmt = select(InvitationCode).where(InvitationCode.code == code.upper().strip())
    return db.execute(stmt).scalars().first()


def validate_code(db: Session, code: str) -> Tuple[bool, str, Optional[InvitationCode]]:
    """
    验证邀请码是否有效
    返回: (is_valid, error_message, invitation_code_object)
    """
    if not code:
        return False, "请输入邀请码", None

    inv_code = get_by_code(db, code)
    if not inv_code:
        return False, "邀请码不存在", None

    if inv_code.status == 0:
        return False, "该邀请码已被禁用", None

    if inv_code.status == 2:
        return False, "该邀请码已过期", None

    # 检查过期时间
    if inv_code.expires_at:
        now = datetime.now(timezone.utc)
        exp = inv_code.expires_at.replace(tzinfo=timezone.utc) if inv_code.expires_at.tzinfo is None else inv_code.expires_at
        if now > exp:
            return False, "该邀请码已过期", None

    # 检查使用次数
    # 如果 max_uses > 1，即使 code_type 是 single_use 也按多次使用处理
    if inv_code.max_uses == 1 and inv_code.used_count >= 1:
        return False, "该邀请码已被使用", None

    if inv_code.max_uses > 1 and inv_code.used_count >= inv_code.max_uses:
        return False, "该邀请码已达到使用上限", None

    # max_uses == 0 表示无限使用，不检查次数

    return True, "", inv_code


def use_code(
    db: Session,
    inv_code: InvitationCode,
    user_id: int,
    ip_address: Optional[str] = None
) -> InvitationCodeUsage:
    """
    记录邀请码使用
    - 增加使用计数
    - 创建使用记录
    """
    # 增加使用计数
    inv_code.used_count += 1

    # 创建使用记录
    usage = InvitationCodeUsage(
        code_id=inv_code.id,
        user_id=user_id,
        ip_address=ip_address[:45] if ip_address else None
    )
    db.add(usage)
    db.flush()
    return usage


def create_invitation_code(
    db: Session,
    *,
    code: Optional[str] = None,
    code_type: str = "single_use",
    max_uses: int = 1,
    expires_at: Optional[datetime] = None,
    created_by: Optional[int] = None,
    note: Optional[str] = None,
) -> InvitationCode:
    """创建新邀请码"""
    if not code:
        code = generate_code()

    inv_code = InvitationCode(
        code=code.upper().strip(),
        code_type=code_type,
        max_uses=max_uses,
        expires_at=expires_at,
        created_by=created_by,
        note=note,
    )
    db.add(inv_code)
    db.flush()
    return inv_code


def list_invitation_codes(
    db: Session,
    *,
    status: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[InvitationCode]:
    """列表查询邀请码"""
    stmt = select(InvitationCode).order_by(InvitationCode.created_at.desc())
    if status is not None:
        stmt = stmt.where(InvitationCode.status == status)
    stmt = stmt.limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def count_invitation_codes(
    db: Session,
    *,
    status: Optional[int] = None,
) -> int:
    """统计邀请码数量"""
    from sqlalchemy import func
    stmt = select(func.count(InvitationCode.id))
    if status is not None:
        stmt = stmt.where(InvitationCode.status == status)
    return db.execute(stmt).scalar() or 0


def disable_code(db: Session, code_id: int) -> Optional[InvitationCode]:
    """禁用邀请码"""
    inv_code = db.get(InvitationCode, code_id)
    if inv_code:
        inv_code.status = 0
        db.flush()
    return inv_code


def enable_code(db: Session, code_id: int) -> Optional[InvitationCode]:
    """启用邀请码"""
    inv_code = db.get(InvitationCode, code_id)
    if inv_code:
        inv_code.status = 1
        db.flush()
    return inv_code


def delete_code(db: Session, code_id: int) -> Optional[InvitationCode]:
    """删除邀请码（软删除，设置status=2）"""
    inv_code = db.get(InvitationCode, code_id)
    if inv_code:
        inv_code.status = 2
        db.flush()
    return inv_code


def get_code_usages(
    db: Session,
    code_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
) -> List[InvitationCodeUsage]:
    """获取邀请码的使用记录"""
    stmt = (
        select(InvitationCodeUsage)
        .where(InvitationCodeUsage.code_id == code_id)
        .order_by(InvitationCodeUsage.used_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())
