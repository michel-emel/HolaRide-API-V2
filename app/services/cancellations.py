from app import models


def get_cancellation_fee_percentage(db, hours_before: float) -> float:
    """
    Finds the right tier from cancellation_policy_tiers for how many
    hours before departure the cancellation happens.

    Tiers are read as "if at least this many hours before departure,
    use this fee %" — checked from the largest min_hours_before down,
    so the closer to departure you are, the higher tier you fall into.
    With the seed defaults (24h->10%, 6h->25%, 0h->50%), cancelling
    10 hours before departure correctly lands on the 25% tier.
    """
    tiers = (
        db.query(models.CancellationPolicyTier)
        .order_by(models.CancellationPolicyTier.min_hours_before.desc())
        .all()
    )
    for tier in tiers:
        if hours_before >= tier.min_hours_before:
            return float(tier.fee_percentage)
    return 0.0  # no tiers configured at all — admin hasn't set any up yet


def apply_reliability_penalty(db, driver_id, trip_id, points: float, event_type: str) -> None:
    """Logs WHY a driver's score changed, and updates the fast-to-read score itself."""
    db.add(models.DriverReliabilityLog(
        driver_id=driver_id, event_type=event_type, points_impact=-points, related_trip_id=trip_id,
    ))
    profile = db.query(models.DriverProfile).filter(models.DriverProfile.user_id == driver_id).first()
    if profile:
        profile.reliability_score = max(0, float(profile.reliability_score) - points)
    db.commit()
