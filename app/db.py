# app/db.py
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# ✅ SQLAlchemy 2.x 推荐：DeclarativeBase
try:
    from sqlalchemy.orm import DeclarativeBase
    class Base(DeclarativeBase):
        pass
except ImportError:  # 兼容 SQLAlchemy 1.4
    from sqlalchemy.ext.declarative import declarative_base
    Base = declarative_base()  # type: ignore

from .config import settings

# ---- Engine 配置 ----
database_url = settings.database_url  # ✅ 使用小写字段
is_sqlite = database_url.startswith("sqlite")

connect_args = {"check_same_thread": False} if is_sqlite else {}

engine = create_engine(
    database_url,
    pool_pre_ping=True,   # 断线自动探活
    connect_args=connect_args,
    future=True,          # 统一使用 2.x 行为
    # echo=True,          # 调试 SQL 时可临时打开
)

# 可选：SQLite开发期常用 PRAGMA（更稳的并发与外键约束）
if is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # 开启外键约束
        cursor.execute("PRAGMA foreign_keys=ON;")
        # 开启 WAL 提高并发（仅本地/开发建议）
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.close()

# ---- Session 工厂 ----
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)

# ---- 依赖注入的会话生成器 ----
def get_db():
    from sqlalchemy.orm import Session
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
