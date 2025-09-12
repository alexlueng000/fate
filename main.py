# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import Base, engine
import app.models as models  # 确保模型注册到 Base（修正原先的导入路径）

# 说明：为避免 /auth/login 路由冲突，这里不再引入旧的 auth.router
# from app.routers import chat, bazi, products, orders, payments, users, entitlements, webhooks
from app.routers import chat, bazi, users, chat_basic


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
            "http://43.139.4.252"
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 已有业务
    app.include_router(chat.router, prefix="/api", tags=["chat"])
    app.include_router(bazi.router, prefix="/api", tags=["bazi"])

    # 新增/本阶段完成的业务
    app.include_router(users.router, prefix="/api", tags=["auth"])  # /api/auth/login, /api/auth/me
    app.include_router(chat_basic.router, prefix="/api", tags=["chat_basic"])

    # 未来业务（保留）
    # app.include_router(products.router, prefix="/api/products", tags=["products"])
    # app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
    # app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
    # app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])
    # app.include_router(entitlements.router, prefix="/api/entitlements", tags=["entitlements"])


    @app.get("/")
    def ping():
        return {"ok": True, "app": settings.app_name}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}
 
    return app


app = create_app()
