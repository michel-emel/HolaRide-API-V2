"""
HR-Skills Pay — Service wrapper.

Routes all requests through Fixie proxy (FIXIE_URL env var) for static IP.
This is required for Vercel deployments so HR-Skills Pay can whitelist the IP.

LIVE keys: Authorization: Bearer KEY_A + X-Transaction-Token (JWT)
SANDBOX keys: same URL, same auth flow
"""
import os
import hmac
import hashlib
import logging
import time
import uuid

import httpx

from app.config import settings

logger = logging.getLogger("holaride.payments")

BASE_URL = "https://api.hrskills-pay.com"
_cached_token: dict | None = None


def _proxy() -> str | None:
    """Return Fixie proxy URL if configured, else None (direct connection)."""
    url = os.environ.get("FIXIE_URL")
    if url:
        logger.debug(f"[HRSkills] Using Fixie proxy: {url[:30]}...")
    return url or None


def _post(url: str, **kwargs) -> httpx.Response:
    proxy = _proxy()
    with httpx.Client(proxy=proxy, timeout=20) as client:
        return client.post(url, **kwargs)


def _get(url: str, **kwargs) -> httpx.Response:
    proxy = _proxy()
    with httpx.Client(proxy=proxy, timeout=15) as client:
        return client.get(url, **kwargs)


def _get_transaction_token() -> str:
    global _cached_token
    now = time.time()
    if _cached_token and _cached_token["expires_at"] - now > 300:
        return _cached_token["token"]

    resp = _post(
        f"{BASE_URL}/v1/auth/transaction-token",
        headers={
            "Authorization": f"Bearer {settings.hrskills_key_a}",
            "Content-Type": "application/json",
        },
        json={"api_secret": settings.hrskills_key_b},
    )
    resp.raise_for_status()
    data = resp.json()
    _cached_token = {
        "token": data["transaction_token"],
        "expires_at": now + data["expires_in"],
    }
    logger.info(f"[HRSkills] Token obtained — env={data.get('environment')}")
    return _cached_token["token"]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.hrskills_key_a}",
        "X-Transaction-Token": _get_transaction_token(),
        "Content-Type": "application/json",
        "Idempotency-Key": str(uuid.uuid4()),
    }


def _detect_operator(phone: str) -> str:
    local = phone.lstrip("+")
    if local.startswith("237"):
        local = local[3:]
    prefix = local[:3]
    mtn    = {"650","651","652","653","654","670","671","672","673","674","675",
              "676","677","678","679","680","681","682","683","684","685","686"}
    orange = {"655","656","657","658","659","690","691","692","693","694","695","696","697","698","699","687","688","689"}
    if prefix in mtn:    return "mtn"
    if prefix in orange: return "orange"
    return "mtn"


def initiate_cashin(
    phone: str,
    amount: float,
    booking_id: str,
    description: str = "HolaRide booking",
) -> dict:
    amount_int  = int(amount)
    phone_clean = phone.lstrip("+")
    operator    = _detect_operator(phone_clean)

    payload = {
        "operator":     operator,
        "country":      "CM",
        "phone_number": phone_clean,
        "amount":       amount_int,
        "currency":     "XAF",
        "description":  description,
        "metadata":     {"booking_id": booking_id},
    }

    proxy_info = "via Fixie" if _proxy() else "direct"
    logger.info(f"[CashIn] booking={booking_id} amount={amount_int} op={operator} ({proxy_info})")

    resp = _post(f"{BASE_URL}/api/v1/payin/mobile-money", headers=_headers(), json=payload)
    resp.raise_for_status()
    data = resp.json()
    logger.info(f"[CashIn] ref={data['data']['reference']} status={data['data']['status']}")
    return data["data"]


def initiate_cashout(phone: str, amount: float, trip_id: str) -> dict:
    amount_int  = int(amount)
    phone_clean = phone.lstrip("+")
    operator    = _detect_operator(phone_clean)

    payload = {
        "operator":     operator,
        "country":      "CM",
        "phone_number": phone_clean,
        "amount":       amount_int,
        "currency":     "XAF",
    }

    logger.info(f"[CashOut] trip={trip_id} amount={amount_int} op={operator}")
    resp = _post(f"{BASE_URL}/api/v1/payout/mobile-money", headers=_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()["data"]


def get_payment_status(reference: str) -> str:
    headers = {
        "Authorization": f"Bearer {settings.hrskills_key_a}",
        "X-Transaction-Token": _get_transaction_token(),
    }
    resp = _get(f"{BASE_URL}/v1/payments/{reference}", headers=headers)
    resp.raise_for_status()
    return resp.json()["data"]["status"]


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    expected = hmac.new(
        settings.hrskills_webhook_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)