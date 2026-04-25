from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
from app.core.database import get_db
from app.core.config import settings
from app.models.user import User
from app.api.v1.deps import get_current_user

router = APIRouter(prefix="/billing", tags=["billing"])

PLAN_NAMES = {"pro": "Про", "team": "Продвинутый"}
PLAN_PRICES_USD = {"pro": 4, "team": 8}
PLAN_PRICES_RUB = {"pro": 400, "team": 800}

# YooKassa notification IPs (https://yookassa.ru/developers/using-api/webhooks)
YOOKASSA_ALLOWED_IPS = {
    "185.71.76.0", "185.71.77.0", "77.75.153.0", "77.75.156.11", "77.75.156.35",
}


def _get_stripe():
    import stripe
    stripe.api_key = settings.stripe_secret_key
    return stripe


def _get_yookassa():
    from yookassa import Configuration, Payment
    Configuration.account_id = settings.yookassa_shop_id
    Configuration.secret_key = settings.yookassa_secret_key
    return Payment


@router.get("/status")
async def get_billing_status(current_user: User = Depends(get_current_user)):
    period_end = None
    if current_user.subscription_current_period_end:
        period_end = current_user.subscription_current_period_end.isoformat()

    return {
        "plan": current_user.plan,
        "subscription_status": current_user.subscription_status,
        "subscription_current_period_end": period_end,
        "stripe_customer_id": current_user.stripe_customer_id,
    }


@router.post("/stripe/create-checkout")
async def create_stripe_checkout(
    plan: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    if plan not in ("pro", "team"):
        raise HTTPException(status_code=400, detail="Invalid plan")

    price_id = settings.stripe_price_pro if plan == "pro" else settings.stripe_price_team
    if not price_id:
        raise HTTPException(status_code=503, detail="Stripe price not configured")

    stripe = _get_stripe()

    customer_id = current_user.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            email=current_user.email,
            name=current_user.name or "",
            metadata={"user_id": current_user.id},
        )
        customer_id = customer.id
        current_user.stripe_customer_id = customer_id
        await db.commit()

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{settings.frontend_url}/dashboard/billing?success=1",
        cancel_url=f"{settings.frontend_url}/dashboard/billing?canceled=1",
        metadata={"user_id": current_user.id, "plan": plan},
    )
    return {"url": session.url}


@router.post("/stripe/portal")
async def create_stripe_portal(current_user: User = Depends(get_current_user)):
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    if not current_user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer found")

    stripe = _get_stripe()
    session = stripe.billing_portal.Session.create(
        customer=current_user.stripe_customer_id,
        return_url=f"{settings.frontend_url}/dashboard/billing",
    )
    return {"url": session.url}


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    stripe = _get_stripe()
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        user_id = data.get("metadata", {}).get("user_id")
        plan = data.get("metadata", {}).get("plan", "pro")
        subscription_id = data.get("subscription")
        if user_id:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.plan = plan
                user.stripe_subscription_id = subscription_id
                user.subscription_status = "active"
                # Will be updated properly on subscription.updated event
                user.subscription_current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
                await db.commit()

    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        customer_id = data.get("customer")
        status = data.get("status")
        period_end_ts = data.get("current_period_end")
        period_end = datetime.fromtimestamp(period_end_ts, tz=timezone.utc) if period_end_ts else None

        result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
        user = result.scalar_one_or_none()
        if user:
            user.stripe_subscription_id = data.get("id")
            user.subscription_status = status
            if period_end:
                user.subscription_current_period_end = period_end
            if status not in ("active", "trialing"):
                user.plan = "free"
            await db.commit()

    elif event_type == "customer.subscription.deleted":
        customer_id = data.get("customer")
        result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
        user = result.scalar_one_or_none()
        if user:
            user.plan = "free"
            user.subscription_status = "canceled"
            user.stripe_subscription_id = None
            await db.commit()

    return {"received": True}


@router.post("/yookassa/create-payment")
async def create_yookassa_payment(
    plan: str,
    current_user: User = Depends(get_current_user),
):
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
        raise HTTPException(status_code=503, detail="YooKassa not configured")
    if plan not in ("pro", "team"):
        raise HTTPException(status_code=400, detail="Invalid plan")

    Payment = _get_yookassa()
    amount_rub = PLAN_PRICES_RUB[plan]
    plan_name = PLAN_NAMES[plan]

    import uuid as uuid_lib
    payment = Payment.create({
        "amount": {"value": str(amount_rub), "currency": "RUB"},
        "confirmation": {
            "type": "redirect",
            "return_url": f"{settings.frontend_url}/dashboard/billing?success=1",
        },
        "capture": True,
        "description": f"TalentFlows {plan_name} — 1 месяц",
        "metadata": {"user_id": current_user.id, "plan": plan},
    }, str(uuid_lib.uuid4()))

    return {"payment_url": payment.confirmation.confirmation_url, "payment_id": payment.id}


@router.post("/yookassa/webhook")
async def yookassa_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    client_ip = request.client.host if request.client else ""
    if client_ip not in YOOKASSA_ALLOWED_IPS:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = body.get("event")
    obj = body.get("object", {})

    if event_type == "payment.succeeded":
        metadata = obj.get("metadata", {})
        user_id = metadata.get("user_id")
        plan = metadata.get("plan", "pro")

        if user_id:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                # Extend or set subscription by 30 days
                now = datetime.now(timezone.utc)
                current_end = user.subscription_current_period_end
                if current_end and current_end > now:
                    new_end = current_end + timedelta(days=30)
                else:
                    new_end = now + timedelta(days=30)

                user.plan = plan
                user.subscription_status = "active"
                user.subscription_current_period_end = new_end
                await db.commit()

    return {"received": True}
