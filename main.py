# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import Base, engine
import app.models as models  # 确保模型注册到 Base（修正原先的导入路径）

# 说明：为避免 /auth/login 路由冲突，这里不再引入旧的 auth.router
from app.routers import chat, bazi, products, orders, payments, users, entitlements, webhooks


def create_app() -> FastAPI:
    # 如已用 init_db.py 初始化，可保留这行作为幂等保障
    Base.metadata.create_all(bind=engine)

    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 已有业务
    app.include_router(chat.router)
    app.include_router(bazi.router)

    # 新增/本阶段完成的业务
    app.include_router(users.router)         # /auth/login, /me
    app.include_router(products.router)      # /products/default, /products/{code}
    app.include_router(orders.router)        # /orders, /orders/my, /orders/{id}
    app.include_router(payments.router)      # /payments/prepay
    app.include_router(webhooks.router)      # /webhooks/wechatpay
    app.include_router(entitlements.router)  # /entitlements/my, /entitlements/{code}

    @app.get("/")
    def ping():
        return {"ok": True, "app": settings.app_name}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()
