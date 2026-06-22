"""
Real PawaPay integration (sandbox by default — see PAWAPAY_BASE_URL
in .env). Replaces the old instant-auto-approve mock.

IMPORTANT — PawaPay's API is ASYNCHRONOUS. Calling charge() or
disburse() only tells you the request was ACCEPTED for processing —
NOT that the money actually moved yet. The customer still has to
approve the charge on their phone (entering their Mobile Money PIN).
The real, final result arrives one of two ways:
  1. A webhook call to POST /payments/webhook/pawapay (configure this
     URL in your PawaPay sandbox dashboard under Developers > Callback
     URLs — for local testing, you need a tool like ngrok to give your
     localhost a public URL PawaPay can actually reach)
  2. Polling check_deposit_status() / check_payout_status() yourself

See app/routers/payments.py for how both paths are wired up.
"""
import uuid

import requests

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("payments_provider")

CAMEROON_CURRENCY = "XAF"


def _headers() -> dict:
    if not settings.pawapay_api_token:
        raise RuntimeError(
            "PAWAPAY_API_TOKEN is not set in your .env file. "
            "Get a sandbox token from your PawaPay dashboard and add it there."
        )
    return {
        "Authorization": f"Bearer {settings.pawapay_api_token}",
        "Content-Type": "application/json",
    }


def predict_provider(phone_number: str) -> dict:
    """
    Asks PawaPay which Mobile Money provider (MTN, Orange, etc.) a
    phone number belongs to, and returns it in the sanitized format
    PawaPay expects. PawaPay's own docs recommend always doing this
    rather than guessing/hardcoding a provider code yourself.

    Returns: {"country": "CMR", "provider": "...", "phoneNumber": "..."}
    """
    resp = requests.post(
        f"{settings.pawapay_base_url}/v2/predict-provider",
        headers=_headers(),
        json={"phoneNumber": phone_number},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def charge(phone_number: str, amount: float) -> dict:
    """
    Initiates a deposit (collecting money FROM a passenger).
    Returns {"provider_transaction_id": <depositId>, "status": "pending" | "rejected"}.
    "pending" here means "PawaPay accepted the request and is now
    waiting for the customer to approve it on their phone" — NOT success yet.
    """
    provider_info = predict_provider(phone_number)
    deposit_id = str(uuid.uuid4())

    resp = requests.post(
        f"{settings.pawapay_base_url}/v2/deposits",
        headers=_headers(),
        json={
            "depositId": deposit_id,
            "payer": {
                "type": "MMO",
                "accountDetails": {
                    "phoneNumber": provider_info["phoneNumber"],
                    "provider": provider_info["provider"],
                },
            },
            "amount": str(int(amount)),  # FCFA has no decimals
            "currency": CAMEROON_CURRENCY,
            "customerMessage": "HolaRide trip payment",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    logger.info(f"[PAWAPAY] deposit {deposit_id} -> {data.get('status')}")

    return {
        "provider_transaction_id": deposit_id,
        "status": "pending" if data.get("status") == "ACCEPTED" else "rejected",
    }


def disburse(phone_number: str, amount: float) -> dict:
    """Initiates a payout (paying OUT to a driver). Same async caveat as charge()."""
    provider_info = predict_provider(phone_number)
    payout_id = str(uuid.uuid4())

    resp = requests.post(
        f"{settings.pawapay_base_url}/v2/payouts",
        headers=_headers(),
        json={
            "payoutId": payout_id,
            "amount": str(int(amount)),
            "currency": CAMEROON_CURRENCY,
            "recipient": {
                "type": "MMO",
                "accountDetails": {
                    "phoneNumber": provider_info["phoneNumber"],
                    "provider": provider_info["provider"],
                },
            },
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    logger.info(f"[PAWAPAY] payout {payout_id} -> {data.get('status')}")

    return {
        "provider_payout_id": payout_id,
        "status": "pending" if data.get("status") == "ACCEPTED" else "rejected",
    }


def check_deposit_status(deposit_id: str) -> str:
    """Returns 'COMPLETED', 'FAILED', or 'PENDING' (still waiting)."""
    resp = requests.get(
        f"{settings.pawapay_base_url}/v2/deposits/{deposit_id}", headers=_headers(), timeout=15
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "FOUND":
        return "PENDING"
    return body["data"]["status"]


def check_payout_status(payout_id: str) -> str:
    """Returns 'COMPLETED', 'FAILED', or 'PENDING' (still waiting)."""
    resp = requests.get(
        f"{settings.pawapay_base_url}/v2/payouts/{payout_id}", headers=_headers(), timeout=15
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "FOUND":
        return "PENDING"
    return body["data"]["status"]
