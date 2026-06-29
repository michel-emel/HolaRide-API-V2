from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import get_current_user
from app.services.trip_access import get_participant_role

router = APIRouter(tags=["reviews"])


def _to_review_out(db: Session, review: models.Review) -> schemas.ReviewOut:
    """Joins in the reviewer's name — without it the app could only show
    a raw UUID next to each review, same problem solved everywhere else
    a sender/owner needed a real name attached."""
    reviewer = db.query(models.User).filter(models.User.id == review.reviewer_id).first()
    return schemas.ReviewOut(
        id=review.id,
        trip_id=review.trip_id,
        reviewer_id=review.reviewer_id,
        reviewee_id=review.reviewee_id,
        reviewer_role=review.reviewer_role,
        stars=review.stars,
        comment=review.comment,
        emoji_reaction=review.emoji_reaction,
        created_at=review.created_at,
        reviewer_first_name=reviewer.first_name if reviewer else None,
        reviewer_last_name=reviewer.last_name if reviewer else None,
    )


@router.post("/trips/{trip_id}/reviews", response_model=schemas.ReviewOut)
def create_review(
    trip_id: UUID,
    payload: schemas.ReviewCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Leaves a review on a completed trip — stars (1-5), an optional
    comment, and an optional quick-reaction emoji. A passenger reviewing
    automatically reviews the driver; a driver reviewing must specify
    which passenger via reviewee_id, since a trip can have several.
    One review per reviewer-reviewee pair per trip.
    """
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.status != "completed":
        raise HTTPException(status_code=400, detail="You can only review a completed trip")
    role = get_participant_role(db, trip, user)
    if not role:
        raise HTTPException(status_code=403, detail="You weren't part of this trip")

    if role == "passenger":
        reviewee_id = trip.driver_id
    else:
        if not payload.reviewee_id:
            raise HTTPException(status_code=400, detail="Specify which passenger you're reviewing (reviewee_id)")
        was_passenger = (
            db.query(models.Booking)
            .filter(
                models.Booking.trip_id == trip.id,
                models.Booking.passenger_id == payload.reviewee_id,
                models.Booking.status.in_(("paid", "completed")),
            )
            .first()
        )
        if not was_passenger:
            raise HTTPException(status_code=400, detail="That person wasn't a passenger on this trip")
        reviewee_id = payload.reviewee_id

    already_reviewed = (
        db.query(models.Review)
        .filter(
            models.Review.trip_id == trip.id,
            models.Review.reviewer_id == user.id,
            models.Review.reviewee_id == reviewee_id,
        )
        .first()
    )
    if already_reviewed:
        raise HTTPException(status_code=400, detail="You already reviewed this person for this trip")

    review = models.Review(
        trip_id=trip.id,
        reviewer_id=user.id,
        reviewee_id=reviewee_id,
        reviewer_role=role,
        stars=payload.stars,
        comment=payload.comment,
        emoji_reaction=payload.emoji_reaction,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return _to_review_out(db, review)


@router.get("/users/{user_id}/reviews", response_model=schemas.ReviewSummary)
def get_user_reviews(user_id: UUID, db: Session = Depends(get_db)):
    """Public. Returns a user's average star rating and full review list — used for either drivers or passengers."""
    reviews = db.query(models.Review).filter(models.Review.reviewee_id == user_id).all()
    if not reviews:
        return schemas.ReviewSummary(average_stars=0, total_reviews=0, reviews=[])
    average = round(sum(r.stars for r in reviews) / len(reviews), 2)
    return schemas.ReviewSummary(
        average_stars=average,
        total_reviews=len(reviews),
        reviews=[_to_review_out(db, r) for r in reviews],
    )


@router.get("/trips/{trip_id}/reviews/pending", response_model=list[schemas.PendingReviewOut])
def get_pending_reviews(
    trip_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    """
    Who the CALLER still needs to review on this trip — drives whether
    the app shows a "Rate this trip" prompt at all, and for whom.
    Empty list (including for a trip that isn't completed yet, or one
    the caller wasn't part of) just means nothing to show right now,
    not an error — a passenger checking before the trip is done
    shouldn't see a confusing failure.
    """
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip or trip.status != "completed":
        return []
    role = get_participant_role(db, trip, user)
    if not role:
        return []

    already_reviewed_ids = {
        row[0]
        for row in db.query(models.Review.reviewee_id)
        .filter(models.Review.trip_id == trip.id, models.Review.reviewer_id == user.id)
        .all()
    }

    pending = []
    if role == "passenger":
        if trip.driver_id not in already_reviewed_ids:
            driver = db.query(models.User).filter(models.User.id == trip.driver_id).first()
            if driver:
                pending.append(
                    schemas.PendingReviewOut(
                        user_id=driver.id, role="driver", first_name=driver.first_name, last_name=driver.last_name
                    )
                )
    else:
        passengers = (
            db.query(models.User)
            .join(models.Booking, models.Booking.passenger_id == models.User.id)
            .filter(
                models.Booking.trip_id == trip.id,
                models.Booking.status.in_(("paid", "completed")),
            )
            .distinct()
            .all()
        )
        for p in passengers:
            if p.id not in already_reviewed_ids:
                pending.append(
                    schemas.PendingReviewOut(user_id=p.id, role="passenger", first_name=p.first_name, last_name=p.last_name)
                )
    return pending
