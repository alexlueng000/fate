# app/services/quota.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models.quota import UserQuota
from app.models.usage_log import UsageLog


class QuotaService:
    """
    配额服务
    - 管理用户的配额（聊天次数、报告次数等）
    - 内测阶段默认无限制 (total_quota = -1)
    """

    # 内测阶段默认无限制
    DEFAULT_FREE_QUOTA = -1

    @staticmethod
    def get_or_create_quota(
        db: Session,
        user_id: int,
        quota_type: str = "chat"
    ) -> UserQuota:
        """
        获取或创建用户配额记录
        """
        quota = db.query(UserQuota).filter(
            UserQuota.user_id == user_id,
            UserQuota.quota_type == quota_type
        ).first()

        if not quota:
            quota = UserQuota(
                user_id=user_id,
                quota_type=quota_type,
                total_quota=QuotaService.DEFAULT_FREE_QUOTA,
                used_quota=0,
                period="never",
                source="free",
            )
            db.add(quota)
            db.commit()
            db.refresh(quota)

        return quota

    @staticmethod
    def check_and_consume(
        db: Session,
        user_id: int,
        quota_type: str = "chat",
        amount: int = 1
    ) -> Tuple[bool, str, int]:
        """
        检查配额并消费
        返回: (是否允许, 消息, 剩余次数)
        """
        quota = QuotaService.get_or_create_quota(db, user_id, quota_type)

        # 检查是否需要重置
        QuotaService.reset_quota_if_needed(db, quota)

        # 无限制
        if quota.total_quota == -1:
            quota.used_quota += amount
            db.commit()
            return True, "无限制", -1

        # 检查剩余配额
        remaining = quota.total_quota - quota.used_quota
        if remaining < amount:
            return False, f"配额不足，剩余 {remaining} 次", remaining

        # 消费配额
        quota.used_quota += amount
        db.commit()

        new_remaining = quota.total_quota - quota.used_quota
        return True, f"剩余 {new_remaining} 次", new_remaining

    @staticmethod
    def reset_quota_if_needed(db: Session, quota: UserQuota) -> None:
        """
        根据 period 重置配额
        """
        if quota.period == "never":
            return

        now = datetime.utcnow()
        last_reset = quota.last_reset_at or quota.created_at

        should_reset = False

        if quota.period == "daily":
            # 每天重置
            if (now - last_reset) >= timedelta(days=1):
                should_reset = True
        elif quota.period == "monthly":
            # 每月重置
            if (now - last_reset) >= timedelta(days=30):
                should_reset = True

        if should_reset:
            quota.used_quota = 0
            quota.last_reset_at = now
            db.commit()

    @staticmethod
    def get_user_stats(db: Session, user_id: int) -> dict:
        """
        获取用户统计信息
        """
        # 获取所有配额
        quotas = db.query(UserQuota).filter(
            UserQuota.user_id == user_id
        ).all()

        # 获取使用日志统计
        from sqlalchemy import func

        # 今日使用次数
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = db.query(func.count(UsageLog.id)).filter(
            UsageLog.user_id == user_id,
            UsageLog.created_at >= today_start
        ).scalar() or 0

        # 总使用次数
        total_count = db.query(func.count(UsageLog.id)).filter(
            UsageLog.user_id == user_id
        ).scalar() or 0

        # 总 token 消耗
        token_stats = db.query(
            func.sum(UsageLog.prompt_tokens),
            func.sum(UsageLog.completion_tokens)
        ).filter(
            UsageLog.user_id == user_id
        ).first()

        total_prompt_tokens = token_stats[0] or 0
        total_completion_tokens = token_stats[1] or 0

        return {
            "quotas": [
                {
                    "type": q.quota_type,
                    "total": q.total_quota,
                    "used": q.used_quota,
                    "remaining": q.remaining,
                    "is_unlimited": q.is_unlimited,
                    "period": q.period,
                    "source": q.source,
                }
                for q in quotas
            ],
            "usage": {
                "today_count": today_count,
                "total_count": total_count,
                "total_prompt_tokens": total_prompt_tokens,
                "total_completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
            }
        }

    @staticmethod
    def set_user_quota(
        db: Session,
        user_id: int,
        quota_type: str,
        total_quota: int,
        period: str = "never",
        source: str = "admin_grant"
    ) -> UserQuota:
        """
        设置用户配额（管理员操作）
        """
        quota = QuotaService.get_or_create_quota(db, user_id, quota_type)
        quota.total_quota = total_quota
        quota.period = period
        quota.source = source
        db.commit()
        db.refresh(quota)
        return quota

    @staticmethod
    def log_usage(
        db: Session,
        user_id: int,
        usage_type: str,
        conversation_id: Optional[int] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0
    ) -> UsageLog:
        """
        记录使用日志
        """
        log = UsageLog(
            user_id=user_id,
            usage_type=usage_type,
            conversation_id=conversation_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log
