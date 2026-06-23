import requests

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("sms")

TERMII_BASE_URL = "https://api.ng.termii.com/api/sms/send"


def send_otp_sms(phone_number: str, code: str) -> None:
    """Sends an OTP code by SMS. Thin wrapper around send_sms() with the OTP-specific message text."""
    send_sms(phone_number, f"Your HolaRide verification code is {code}")


def send_sms(phone_number: str, message: str) -> None:
    """
    Sends ANY text message — OTP codes, booking request/accept/reject
    alerts, anything. Once OTP_DEV_MODE is false, this is a REAL SMS
    that costs real money via whichever provider SMS_PROVIDER points
    to. In dev mode, it just logs instead — never sends anything real,
    which matters a lot here since quick_test.py runs this exact path
    repeatedly with fake phone numbers.
    """
    if settings.otp_dev_mode:
        logger.info(f"[DEV SMS] {phone_number} -> {message}")
        return

    if settings.sms_provider == "termii":
        _send_via_termii(phone_number, message)
    elif settings.sms_provider == "twilio":
        _send_via_twilio(phone_number, message)
    else:
        raise RuntimeError(f"Unknown SMS_PROVIDER: {settings.sms_provider!r}")


def _send_via_termii(phone_number: str, message: str) -> None:
    """
    Termii's docs recommend the 'dnd' channel for OTP/transactional
    messages (the 'generic' channel is for promotional messages and
    can fail or get your sender ID blocked if used for OTPs). 'dnd'
    needs to be activated on your account first via Termii support —
    see TERMII_CHANNEL in .env if you need a temporary fallback.
    """
    if not (settings.termii_api_key and settings.termii_sender_id):
        raise RuntimeError(
            "OTP_DEV_MODE is false and SMS_PROVIDER=termii, but Termii isn't "
            "fully configured. Set TERMII_API_KEY and TERMII_SENDER_ID in .env."
        )

    # Termii expects numbers WITHOUT the leading '+', e.g. 237691234567
    to_number = phone_number.lstrip("+")

    resp = requests.post(
        TERMII_BASE_URL,
        headers={"Content-Type": "application/json"},
        json={
            "api_key": settings.termii_api_key,
            "to": to_number,
            "from": settings.termii_sender_id,
            "sms": message,
            "type": "plain",
            "channel": settings.termii_channel,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != "ok":
        logger.error(f"[TERMII] send failed for {phone_number}: {data}")
        raise RuntimeError(f"Termii failed to send: {data.get('message', 'unknown error')}")

    logger.info(f"[TERMII] SMS sent to {phone_number}, message_id={data.get('message_id')}")


def _send_via_twilio(phone_number: str, message: str) -> None:
    """
    Twilio TRIAL ACCOUNT NOTE: trial accounts can only send to phone
    numbers you've manually verified in the Twilio console first
    (console.twilio.com -> Phone Numbers -> Verified Caller IDs).
    """
    from twilio.rest import Client  # imported here so it's never required unless actually used

    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number):
        raise RuntimeError(
            "OTP_DEV_MODE is false and SMS_PROVIDER=twilio, but Twilio isn't "
            "fully configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
            "and TWILIO_FROM_NUMBER in .env."
        )

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    sent = client.messages.create(body=message, from_=settings.twilio_from_number, to=phone_number)
    logger.info(f"[TWILIO] SMS sent to {phone_number}, message sid={sent.sid}")
