# app/db.py
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


# -----------------------------
# Declarative Base
# -----------------------------
class Base(DeclarativeBase):
    pass


# -----------------------------
# URL 规范化（允许写 mysql://）
# -----------------------------
def _normalize_url(url: str) -> str:
    if url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+pymysql://", 1)
    return url


# -----------------------------
# Engine 配置（仅 MySQL）
# -----------------------------
database_url: str = _normalize_url(settings.database_url)

engine = create_engine(
    database_url,
    future=True,          # 统一 2.x 行为
    pool_pre_ping=True,   # 断线自动探活
    pool_size=getattr(settings, "db_pool_size", 10),
    max_overflow=getattr(settings, "db_max_overflow", 20),
    pool_recycle=getattr(settings, "db_pool_recycle", 3600),  # 1 小时回收
    pool_timeout=getattr(settings, "db_pool_timeout", 30),
    # echo=True,          # 调试时可打开
)

# 可选：时区/严格模式（这里用 connect 事件逐条执行，避免 init_command 多语句问题）
_DB_TZ = getattr(settings, "db_time_zone", "+00:00")
_DB_STRICT = bool(getattr(settings, "db_strict_mode", True))


@event.listens_for(engine, "connect")
def _mysql_session_init(dbapi_conn, conn_record):
    with dbapi_conn.cursor() as cur:
        # 设置时区（可改成 '+08:00'）
        if _DB_TZ:
            # 用参数化，避免引号问题
            cur.execute("SET time_zone = %s", (_DB_TZ,))
        # 开启严格模式，避免静默截断
        if _DB_STRICT:
            cur.execute("SET SESSION sql_mode = 'STRICT_ALL_TABLES'")


# -----------------------------
# Session 工厂
# -----------------------------
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


# -----------------------------
# FastAPI 依赖 & 脚本工具
# -----------------------------
def get_db() -> Generator[Session, None, None]:
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_tx() -> Generator[Session, None, None]:
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def dispose_engine() -> None:
    try:
        engine.dispose()
    except Exception:
        pass
