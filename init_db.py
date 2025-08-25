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
        "code": "REPORT_UNLOCK",
        "name": "报告解锁",
        "price_cents": 990,
        "currency": "CNY",
        "active": True,
    },
    {
        "code": "VIP_30D",
        "name": "VIP 30 天",
        "price_cents": 1990,
        "currency": "CNY",
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
    seed_products()


if __name__ == "__main__":
    main()