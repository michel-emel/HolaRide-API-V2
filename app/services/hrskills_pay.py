"""
HR-Skills Pay — Service wrapper.
Keys from env: HRSKILLS_KEY_A, HRSKILLS_KEY_B, HRSKILLS_SANDBOX

Sandbox (TEST keys):  base URL = https://api.hrskills-pay.com/sandbox/v1/
Production (LIVE keys): base URL = https://api.hrskills-pay.com

Sandbox rule: even amount = SUCCESS, odd amount = FAILED
"""
import hmac
import hashlib
import logging
import time
import uuid

import httpx

from app.config import settings

logger = logging.getLogger("holaride.payments")

BASE_URL    = "https://api.hrskills-pay.com"
SANDBOX_URL = "https://api.hrskills-pay.com/sandbox/api"

_cached_token: dict | None = None


def _api_base() -> str:
    """Returns the correct base URL depending on sandbox mode."""
    return SANDBOX_URL if settings.hrskills_sandbox else BASE_URL


def _get_transaction_token() -> str:
    """Return a valid transaction token, refreshing if < 5 min left."""
    global _cached_token
    now = time.time()
    if _cached_token and _cached_token["expires_at"] - now > 300:
        return _cached_token["token"]

    resp = httpx.post(
        f"{BASE_URL}/v1/auth/transaction-token",   # token endpoint is always on BASE_URL
        headers={
            "Authorization": f"Bearer {settings.hrskills_key_a}",
            "Content-Type": "application/json",
        },
        json={"api_secret": settings.hrskills_key_b},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _cached_token = {
        "token": data["transaction_token"],
        "expires_at": now + data["expires_in"],
    }
    logger.info(f"[HRSkills] New transaction token — env={data.get('environment')} expires_in={data.get('expires_in')}s")
    return _cached_token["token"]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.hrskills_key_a}",
        "X-Transaction-Token": _get_transaction_token(),
        "Content-Type": "application/json",
        "Idempotency-Key": str(uuid.uuid4()),
    }


def _detect_operator(phone: str) -> str:
    """Detect MTN or Orange from Cameroon phone prefix."""
    local = phone.lstrip("+")
    if local.startswith("237"):
        local = local[3:]
    prefix = local[:3]
    mtn = {
        "650","651","652","653","654","670","671","672","673","674","675",
        "676","677","678","679","680","681","682","683","684","685","686","687","688","689",
    }
    orange = {"655","656","657","658","659","690","691","692","693","694","695","696","697","698","699"}
    if prefix in mtn:    return "mtn"
    if prefix in orange: return "orange"
    return "mtn"


def _sandbox_amount(amount: float) -> int:
    """Sandbox: amount must be even for SUCCESS, odd for FAILED."""
    n = int(amount)
    return n if n % 2 == 0 else n + 1


def initiate_cashin(
    phone: str,
    amount: float,
    booking_id: str,
    description: str = "HolaRide booking",
) -> dict:
    """
    Initiate Mobile Money Cash-In for a passenger booking.
    Returns the HR-Skills Pay data dict (includes reference + status PENDING).
    """
    amount_int  = _sandbox_amount(amount) if settings.hrskills_sandbox else int(amount)
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

    url = f"{_api_base()}/v1/payin/mobile-money"
    logger.info(f"[CashIn] booking={booking_id} amount={amount_int} op={operator} url={url}")

    resp = httpx.post(url, headers=_headers(), json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    logger.info(f"[CashIn] ref={data['data']['reference']} status={data['data']['status']}")
    return data["data"]


def initiate_cashout(
    phone: str,
    amount: float,
    trip_id: str,
) -> dict:
    """Send payout to driver when trip is completed."""
    amount_int  = _sandbox_amount(amount) if settings.hrskills_sandbox else int(amount)
    phone_clean = phone.lstrip("+")
    operator    = _detect_operator(phone_clean)

    payload = {
        "operator":     operator,
        "country":      "CM",
        "phone_number": phone_clean,
        "amount":       amount_int,
        "currency":     "XAF",
    }

    url = f"{_api_base()}/v1/payout/mobile-money"
    logger.info(f"[CashOut] trip={trip_id} amount={amount_int} op={operator}")

    resp = httpx.post(url, headers=_headers(), json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data["data"]


def get_payment_status(reference: str) -> str:
    """
    Poll payment status.
    Returns: PENDING | SUCCESS | FAILED | HOLD | REFUNDED
    """
    resp = httpx.get(
        f"{BASE_URL}/v1/payments/{reference}",    # status always on BASE_URL
        headers={
            "Authorization": f"Bearer {settings.hrskills_key_a}",
            "X-Transaction-Token": _get_transaction_token(),
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["data"]["status"]


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify X-Hub-Signature header from HR-Skills Pay webhook."""
    expected = hmac.new(
        settings.hrskills_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)