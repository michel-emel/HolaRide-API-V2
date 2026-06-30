import requests
from app.config import settings
from app.logging_config import get_logger

logger = get_logger("sms")


def send_otp_sms(phone_number: str, code: str) -> None:
    """Sends an OTP code by SMS. Thin wrapper around send_sms() with the OTP-specific message text."""
    send_sms(phone_number, f"Hello User, your HolaRide verification code is {code}")


def send_sms(phone_number: str, message: str) -> None:
    """
    Sends ANY text message — OTP codes, booking request/accept/reject
    alerts, anything. Once OTP_DEV_MODE is false, this is a REAL SMS
    that costs real money via Infobip. In dev mode, it just logs
    instead — never sends anything real, which matters a lot here
    since quick_test.py runs this exact path repeatedly with fake
    phone numbers.
    """
    if settings.otp_dev_mode:
        logger.info(f"[DEV SMS] {phone_number} -> {message}")
        return
    _send_via_infobip(phone_number, message)


def _send_via_infobip(phone_number: str, message: str) -> None:
    """
    INFOBIP TRIAL ACCOUNT NOTES, confirmed from your own working cURL
    test:
    - The base URL is account-specific (e.g. "2yr9vp.api.infobip.com"),
      NOT a shared domain — copy yours exactly from your Infobip
      dashboard into INFOBIP_BASE_URL, no "https://" prefix needed
      here since it's added below.
    - The trial sender is literally the string "ServiceSMS" — Infobip
      substitutes any custom sender name to this on a trial account
      regardless of what's sent, so INFOBIP_SENDER_ID defaults to that
      below. Once you register a real sender ID with Infobip for
      production, set INFOBIP_SENDER_ID to that instead.
    - The trial only allows 14 total messages and only to numbers
      verified during signup — both stop applying once you add real
      credit to the account.

    Phone numbers are sent WITHOUT the leading '+' — confirmed from
    your own cURL test ("to": "237674546957").
    """
    if not (settings.infobip_api_key and settings.infobip_base_url):
        raise RuntimeError(
            "OTP_DEV_MODE is false, but Infobip isn't fully configured. "
            "Set INFOBIP_API_KEY and INFOBIP_BASE_URL in .env."
        )
    to_number = phone_number.lstrip("+")
    resp = requests.post(
        f"https://{settings.infobip_base_url}/sms/3/messages",
        headers={
            "Authorization": f"App {settings.infobip_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={
            "messages": [
                {
                    "destinations": [{"to": to_number}],
                    "sender": settings.infobip_sender_id,
                    "content": {"text": message},
                }
            ]
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    # Infobip returns one status block per message, even for a
    # single-recipient send — status.groupName "PENDING" or
    # "DELIVERED" means it was accepted; "REJECTED" or similar means
    # it wasn't. Checking this explicitly rather than just trusting a
    # 200 status code, since Infobip can return 200 with a per-message
    # rejection inside the body (e.g. invalid number, blocked sender).
    try:
        message_result = data["messages"][0]
        status = message_result["status"]
    except (KeyError, IndexError) as exc:
        logger.error(f"[INFOBIP] unexpected response shape for {phone_number}: {data}")
        raise RuntimeError("Infobip returned an unexpected response shape") from exc

    if status.get("groupName") == "REJECTED":
        logger.error(f"[INFOBIP] send rejected for {phone_number}: {status}")
        raise RuntimeError(f"Infobip rejected the message: {status.get('description', 'unknown reason')}")

    logger.info(
        f"[INFOBIP] SMS sent to {phone_number}, message_id={message_result.get('messageId')}, "
        f"status={status.get('name')}"
    )