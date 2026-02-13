# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import Base, engine
from app.core.logging import setup_logging
from app.middleware.logging import RequestLoggingMiddleware
import app.models as models  # 确保模型注册到 Base（修正原先的导入路径）

# 初始化日志系统
logger = setup_logging(log_level="INFO")

# 说明：为避免 /auth/login 路由冲突，这里不再引入旧的 auth.router
# from app.routers import chat, bazi, products, orders, payments, users, entitlements, webhooks
from app.routers import chat, bazi, users, chat_basic, admin, config_public, kb, invitation_codes, sensitive_words, feedback, admin_stats, user_stats


def create_app() -> FastAPI:
    # 如已用 init_db.py 初始化，可保留这行作为幂等保障
    Base.metadata.create_all(bind=engine)

    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "https://yizhanmaster.site",
            "http://43.139.4.252:3000",
            "http://43.139.4.252",
            "https://api.fateinsight.site"
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 添加请求日志中间件
    app.add_middleware(RequestLoggingMiddleware)

    # 已有业务
    app.include_router(chat.router, prefix="/api", tags=["chat"])
    app.include_router(bazi.router, prefix="/api", tags=["bazi"])

    # 新增/本阶段完成的业务
    app.include_router(users.router, prefix="/api", tags=["auth"])  # /api/auth/login, /api/auth/me
    app.include_router(chat_basic.router, prefix="/api", tags=["chat_basic"])
    app.include_router(admin.router, prefix="/api", tags=["admin"])
    app.include_router(config_public.router, prefix="/api", tags=["config_public"])
    app.include_router(kb.router, prefix="/api", tags=["kb"])
    app.include_router(invitation_codes.router, prefix="/api", tags=["invitation-codes"])
    app.include_router(sensitive_words.router, prefix="/api", tags=["sensitive-words"])
    app.include_router(feedback.router, prefix="/api", tags=["feedback"])
    app.include_router(admin_stats.router, prefix="/api", tags=["admin-stats"])
    app.include_router(user_stats.router, prefix="/api", tags=["user-stats"])

    # 未来业务（保留）
    # app.include_router(products.router, prefix="/api/products", tags=["products"])
    # app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
    # app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
    # app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])
    # app.include_router(entitlements.router, prefix="/api/entitlements", tags=["entitlements"])


    @app.get("/api/ping")
    def ping():
        return {"ok": True, "app": settings.app_name}

    @app.get("/api/healthz")
    def healthz():
        return {"status": "ok"}

    @app.on_event("startup")
    async def startup():
        logger.info("application_started", version="1.0.0")

    @app.on_event("shutdown")
    async def shutdown():
        logger.info("application_stopped")

    return app


app = create_app()
