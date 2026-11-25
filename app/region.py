"""Server-owned deployment policy, independent of client language."""
from fastapi import HTTPException
from app.config import settings
from app.i18n import payments_unavailable


def payments_enabled() -> bool:
    return settings.fate_region == "cn" and settings.fate_payments_enabled


def require_payments() -> None:
    if not payments_enabled():
        raise HTTPException(status_code=403, detail=payments_unavailable())


def require_payment_service() -> None:
    if not payments_enabled():
        raise ValueError(payments_unavailable())
