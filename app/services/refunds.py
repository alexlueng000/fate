from __future__ import annotations

import json
import secrets
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    MembershipGrant,
    Order,
    Payment,
    QuotaLedger,
    Refund,
    UserMembership,
    UserQuota,
)
from app.services.payments import _wechat_auth_header, verify_wechat_response


class RefundRequestError(Exception):
    """Base class for refund request validation failures."""


class RefundOrderNotFound(RefundRequestError):
    pass


class RefundNotAllowed(RefundRequestError):
    pass


class WeChatRefundError(RefundRequestError):
    pass


def _generate_out_refund_no(order_id: int) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"RF{timestamp}{order_id}{secrets.token_hex(4).upper()}"


def _latest_successful_wechat_payment(db: Session, order_id: int) -> Payment | None:
    stmt = (
        select(Payment)
        .where(
            Payment.order_id == order_id,
            Payment.status == "SUCCESS",
            Payment.channel.in_(("WECHAT_NATIVE", "WECHAT_JSAPI")),
        )
        .order_by(Payment.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def _refund_notify_url() -> str:
    if settings.wechat_pay_refund_notify_url:
        return settings.wechat_pay_refund_notify_url
    if settings.wechat_pay_notify_url:
        return f"{settings.wechat_pay_notify_url.rstrip('/')}/refund"
    if settings.wechat_pay_mode != "prod":
        return "https://example.invalid/api/webhooks/wechatpay/refund"
    raise WeChatRefundError("WECHAT_PAY_REFUND_NOTIFY_URL is not configured")


def _wechat_refund_headers(method: str, url_path: str, body: str = "") -> dict[str, str]:
    return {
        "Authorization": _wechat_auth_header(method, url_path, body),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "fateinsight/1.0",
    }


def _expected_entitlement_traces(refund: Refund) -> tuple[bool, bool]:
    product = refund.order.product
    has_product_grants = any(grant.amount > 0 for grant in product.grants)
    expects_quota = has_product_grants or any(
        amount and amount > 0
        for amount in (
            product.bazi_quota,
            product.liuyao_quota,
            product.quota_amount,
        )
    )
    expects_membership = product.kind == "subscription"
    return expects_quota, expects_membership


def finalize_successful_refund(db: Session, *, refund: Refund) -> bool:
    """Idempotently revoke the refunded order's traceable entitlements."""

    if refund.status != "SUCCESS":
        return False
    if refund.order.status == "REFUNDED":
        return True

    purchase_ledgers = list(
        db.execute(
            select(QuotaLedger)
            .where(
                QuotaLedger.order_id == refund.order_id,
                QuotaLedger.event_type == "PURCHASE_GRANT",
                QuotaLedger.delta > 0,
            )
            .with_for_update()
        ).scalars().all()
    )
    membership_grant = db.execute(
        select(MembershipGrant)
        .where(MembershipGrant.order_id == refund.order_id)
        .with_for_update()
    ).scalars().first()

    expects_quota, expects_membership = _expected_entitlement_traces(refund)
    missing = []
    if expects_quota and not purchase_ledgers:
        missing.append("quota_ledger")
    if expects_membership and not membership_grant:
        missing.append("membership_grant")
    if missing:
        refund.failure_code = "ENTITLEMENT_TRACE_MISSING"
        refund.failure_message = f"缺少权益追踪记录: {', '.join(missing)}"
        db.flush()
        return False

    granted_by_type: dict[str, int] = {}
    for ledger in purchase_ledgers:
        granted_by_type[ledger.quota_type] = (
            granted_by_type.get(ledger.quota_type, 0) + ledger.delta
        )

    for quota_type, granted_amount in granted_by_type.items():
        idempotency_key = f"refund:{refund.id}:quota:{quota_type}:reversal"
        existing_reversal = db.execute(
            select(QuotaLedger).where(
                QuotaLedger.idempotency_key == idempotency_key
            )
        ).scalars().first()
        if existing_reversal:
            continue

        quota = db.execute(
            select(UserQuota)
            .where(
                UserQuota.user_id == refund.user_id,
                UserQuota.quota_type == quota_type,
            )
            .with_for_update()
        ).scalars().first()

        reclaimed = 0
        if quota and quota.total_quota != -1:
            available = max(0, quota.total_quota - quota.used_quota)
            reclaimed = min(granted_amount, available)
            quota.total_quota -= reclaimed
            quota.source = "refund"

        db.add(
            QuotaLedger(
                user_id=refund.user_id,
                quota_type=quota_type,
                delta=-granted_amount,
                event_type="REFUND_REVERSAL",
                order_id=refund.order_id,
                refund_id=refund.id,
                idempotency_key=idempotency_key,
                note=(
                    f"granted={granted_amount};reclaimed={reclaimed};"
                    f"unrecovered={granted_amount - reclaimed}"
                ),
            )
        )

    if membership_grant and membership_grant.status != "REVOKED":
        membership = db.execute(
            select(UserMembership)
            .where(
                UserMembership.user_id == membership_grant.user_id,
                UserMembership.product_id == membership_grant.product_id,
            )
            .order_by(UserMembership.current_period_end.desc())
            .limit(1)
            .with_for_update()
        ).scalars().first()

        now = datetime.utcnow()
        duration = membership_grant.ends_at - membership_grant.starts_at
        membership_grant.status = "REVOKED"
        membership_grant.refund_id = refund.id
        membership_grant.revoked_at = now

        if membership:
            membership.current_period_end = max(
                membership.current_period_start,
                membership.current_period_end - duration,
            )
            if membership.current_period_end <= now:
                membership.status = "cancelled"
                membership.cancelled_at = now

            if membership.order_id == refund.order_id:
                latest_active_grant = db.execute(
                    select(MembershipGrant)
                    .where(
                        MembershipGrant.user_id == membership_grant.user_id,
                        MembershipGrant.product_id == membership_grant.product_id,
                        MembershipGrant.status == "ACTIVE",
                        MembershipGrant.order_id != refund.order_id,
                    )
                    .order_by(MembershipGrant.ends_at.desc())
                    .limit(1)
                ).scalars().first()
                membership.order_id = (
                    latest_active_grant.order_id if latest_active_grant else None
                )

    refund.order.status = "REFUNDED"
    refund.failure_code = None
    refund.failure_message = None
    db.flush()
    return True


def sync_refund_state(
    db: Session,
    *,
    refund: Refund,
    data: dict,
    raw_response: str,
) -> Refund:
    """Apply a verified WeChat refund response or callback idempotently."""

    wechat_status = str(data.get("status") or data.get("refund_status") or "")
    status_map = {
        "PROCESSING": "PROCESSING",
        "SUCCESS": "SUCCESS",
        "CLOSED": "CLOSED",
        "ABNORMAL": "ABNORMAL",
    }
    local_status = status_map.get(wechat_status)
    if not local_status:
        raise WeChatRefundError(f"Unknown WeChat refund status: {wechat_status}")

    # A delayed query response must never overwrite a newer terminal callback.
    state_rank = {
        "CREATED": 0,
        "FAILED": 0,
        "PROCESSING": 1,
        "CLOSED": 2,
        "ABNORMAL": 2,
        "SUCCESS": 3,
    }
    if state_rank.get(local_status, 0) < state_rank.get(refund.status, 0):
        return refund

    refund.status = local_status
    refund.wechat_refund_id = data.get("refund_id") or refund.wechat_refund_id
    refund.raw_response = raw_response
    refund.failure_code = None
    refund.failure_message = None
    if local_status == "SUCCESS" and refund.success_at is None:
        refund.success_at = datetime.utcnow()
    elif local_status == "CLOSED":
        refund.order.status = "PAID"

    db.flush()
    if local_status == "SUCCESS":
        finalize_successful_refund(db, refund=refund)
    return refund


def submit_wechat_refund(db: Session, *, refund: Refund) -> Refund:
    """Submit a local refund to WeChat, reusing its merchant refund number."""

    if refund.status in {"PROCESSING", "SUCCESS", "ABNORMAL"}:
        return refund

    payment = _latest_successful_wechat_payment(db, refund.order_id)
    if not payment or not payment.transaction_id:
        raise WeChatRefundError("未找到成功的微信支付交易记录")

    body_data = {
        "transaction_id": payment.transaction_id,
        "out_refund_no": refund.out_refund_no,
        "reason": refund.reason,
        "notify_url": _refund_notify_url(),
        "amount": {
            "refund": refund.refund_cents,
            "total": refund.total_cents,
            "currency": refund.currency,
        },
    }
    body = json.dumps(body_data, ensure_ascii=False, separators=(",", ":"))
    refund.raw_request = body

    if settings.wechat_pay_mode != "prod":
        return sync_refund_state(
            db,
            refund=refund,
            data={
                "refund_id": f"dev_refund_{refund.id}",
                "status": "PROCESSING",
            },
            raw_response=json.dumps(
                {"mode": "dev", "status": "PROCESSING"}, ensure_ascii=False
            ),
        )

    url_path = "/v3/refund/domestic/refunds"
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(
                f"https://api.mch.weixin.qq.com{url_path}",
                content=body.encode("utf-8"),
                headers=_wechat_refund_headers("POST", url_path, body),
            )
        if response.status_code >= 400:
            try:
                error = response.json() if response.content else {}
            except ValueError:
                error = {}
            refund.status = "FAILED"
            refund.raw_response = response.text
            refund.failure_code = str(error.get("code") or response.status_code)
            refund.failure_message = str(error.get("message") or "微信退款申请失败")
            db.flush()
            raise WeChatRefundError(refund.failure_message)

        verify_wechat_response(response)
        return sync_refund_state(
            db,
            refund=refund,
            data=response.json(),
            raw_response=response.text,
        )
    except WeChatRefundError:
        raise
    except Exception as exc:
        refund.status = "FAILED"
        refund.failure_code = type(exc).__name__
        refund.failure_message = str(exc)[:512]
        db.flush()
        raise WeChatRefundError("调用微信退款接口失败") from exc


def query_wechat_refund(db: Session, *, refund: Refund) -> Refund:
    """Query WeChat using the stable merchant refund number and sync state."""

    if settings.wechat_pay_mode != "prod":
        return refund

    url_path = f"/v3/refund/domestic/refunds/{refund.out_refund_no}"
    try:
        with httpx.Client(timeout=15) as client:
            response = client.get(
                f"https://api.mch.weixin.qq.com{url_path}",
                headers=_wechat_refund_headers("GET", url_path),
            )
        if response.status_code >= 400:
            try:
                error = response.json() if response.content else {}
            except ValueError:
                error = {}
            refund.failure_code = str(error.get("code") or response.status_code)
            refund.failure_message = str(error.get("message") or "微信退款查询失败")
            db.flush()
            raise WeChatRefundError(refund.failure_message)

        verify_wechat_response(response)
        return sync_refund_state(
            db,
            refund=refund,
            data=response.json(),
            raw_response=response.text,
        )
    except WeChatRefundError:
        raise
    except Exception as exc:
        refund.failure_code = type(exc).__name__
        refund.failure_message = str(exc)[:512]
        db.flush()
        raise WeChatRefundError("查询微信退款状态失败") from exc


def create_full_refund_request(
    db: Session,
    *,
    order_id: int,
    requested_by: int,
    reason: str,
) -> Refund:
    """Create an idempotent local full-refund request for a paid WeChat order."""

    order = db.execute(
        select(Order).where(Order.id == order_id).with_for_update()
    ).scalars().first()
    if not order:
        raise RefundOrderNotFound("订单不存在")

    existing = db.execute(
        select(Refund)
        .where(Refund.order_id == order.id)
        .order_by(Refund.id.desc())
        .limit(1)
    ).scalars().first()
    if existing:
        return existing

    if order.status != "PAID":
        raise RefundNotAllowed(f"订单状态为 {order.status}，不能申请退款")
    if order.amount_cents <= 0:
        raise RefundNotAllowed("订单实付金额必须大于零")
    if order.currency != "CNY":
        raise RefundNotAllowed("当前仅支持人民币微信支付订单退款")

    payment = _latest_successful_wechat_payment(db, order.id)
    if not payment or not payment.transaction_id:
        raise RefundNotAllowed("未找到成功的微信支付交易记录")

    clean_reason = reason.strip()
    if not clean_reason:
        raise RefundNotAllowed("退款原因不能为空")

    refund = Refund(
        order_id=order.id,
        user_id=order.user_id,
        out_refund_no=_generate_out_refund_no(order.id),
        refund_cents=order.amount_cents,
        total_cents=order.amount_cents,
        currency=order.currency,
        reason=clean_reason,
        status="CREATED",
        requested_by=requested_by,
    )
    db.add(refund)
    order.status = "REFUNDING"
    db.flush()
    return refund
