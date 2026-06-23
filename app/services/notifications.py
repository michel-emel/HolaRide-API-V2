from app import models
from app.logging_config import get_logger
from app.services.sms import send_sms

logger = get_logger("notifications")


def notify_user(db, user_id, type_: str, title: str, body: str, channel: str = "push") -> None:
    """
    Always logs the notification to the `notifications` table — that
    part never changes. If channel="sms", ALSO actually sends a real
    text via send_sms() (which itself still respects OTP_DEV_MODE —
    logs instead of sending for real during local dev/testing).

    "push" isn't wired to a real push provider yet (no Firebase/APNs
    integration exists) — it just logs, same as before, until that's built.
    """
    notif = models.Notification(
        user_id=user_id, type=type_, title=title, body=body, channel=channel, status="sent"
    )
    db.add(notif)
    db.commit()
    logger.info(f"[NOTIFY] -> user {user_id} via {channel}: {title} | {body}")

    if channel == "sms":
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            logger.warning(f"Tried to SMS notify user {user_id} but no such user exists")
            return
        try:
            send_sms(user.phone_number, body)
        except Exception as exc:
            logger.error(f"Failed to send SMS notification to {user.phone_number}: {exc}")
            notif.status = "failed"
            db.commit()
