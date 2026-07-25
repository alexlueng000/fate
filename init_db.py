# app/db/init_db.py
from __future__ import annotations

import logging
from typing import Iterable

from app.db import Base, engine, session_scope
# 一定要导入 models 才能把所有 Table 注册到 Base.metadata
import app.models as models  # noqa: F401

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(message)s",
)

# ---- 可选：最小化种子数据（按需修改/删除） ----
SEED_PRODUCTS: Iterable[dict] = [
    {
        "code": "membership_basic_1990",
        "kind": "subscription",
        "period": "monthly",
        "name": "传统文化 AI 基础会员",
        "price_cents": 1990,
        "currency": "CNY",
        "quota_amount": 0,
        "bazi_quota": 30,
        "liuyao_quota": 30,
        "description": "30 天传统文化会员权益，含 30 次八字文化 AI 对话、30 次六爻文化卦象解析和会员课程。",
        "features": {"tier": "basic", "video_access": True},
        "active": True,
    },
    {
        "code": "monthly_3990",
        "kind": "subscription",
        "period": "monthly",
        "name": "传统文化 AI 高级会员",
        "price_cents": 3990,
        "currency": "CNY",
        "quota_amount": 0,
        "bazi_quota": 100,
        "liuyao_quota": 100,
        "description": "30 天传统文化高级会员权益，含 100 次八字文化 AI 对话、100 次六爻文化卦象解析和会员课程。",
        "features": {"tier": "premium", "video_access": True},
        "active": True,
    },
    {
        "code": "topup_2000",
        "kind": "topup",
        "period": None,
        "name": "叠加包",
        "price_cents": 2000,
        "currency": "CNY",
        "quota_amount": 0,
        "bazi_quota": 50,
        "liuyao_quota": 50,
        "description": "额外增加 50 次八字文化 AI 对话和 50 次六爻文化卦象解析。",
        "features": {"validity": "跟随当前会员期；非会员购买默认 30 天有效"},
        "active": True,
    },
]


def create_tables() -> None:
    """
    创建所有表（幂等）。等价于 Alembic 之前的最小方案。
    """
    logger.info("Creating database tables (if not exist)...")
    Base.metadata.create_all(bind=engine, checkfirst=True)
    logger.info("All tables are up to date.")


def seed_products() -> None:
    """
    写入最小化商品种子数据（仅在不存在时插入，不修改已存在记录）。
    """
    from app.models import Product  # 本地导入，避免循环依赖

    inserted = 0
    with session_scope() as db:
        existing_codes = {
            code for (code,) in db.query(Product.code).all()
        }
        for item in SEED_PRODUCTS:
            if item["code"] in existing_codes:
                continue
            db.add(Product(**item))
            inserted += 1

    if inserted:
        logger.info("Seeded %d product(s).", inserted)
    else:
        logger.info("No products seeded (all present).")


def main() -> None:
    create_tables()
    # 如不想自动灌入数据，注释掉下一行即可
    # seed_products()


if __name__ == "__main__":
    main()
