from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.db import Base, engine
from app import models
from app.routers import auth, chat, bazi, products, orders, payments

# def bootstrap_data():
#     from sqlalchemy.orm import Session
#     with Session(engine) as db:
#         if not db.query(models.Product).first():
#             db.add_all([
#                 models.Product(sku="REPORT_PRO", name="深度解读报告", type="oneoff", price=1990, currency="CNY", active=True),
#                 models.Product(sku="VIP_MONTH", name="月度会员", type="subscription", price=4900, currency="CNY", active=True),
#             ])
#             db.commit()

def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)
    # bootstrap_data()

    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_allow_origins] if settings.cors_allow_origins != "*" else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(bazi.router)
    app.include_router(products.router)
    app.include_router(orders.router)
    app.include_router(payments.router)

    @app.get("/")
    def ping():
        return {"ok": True, "app": settings.app_name}

    return app

app = create_app()
