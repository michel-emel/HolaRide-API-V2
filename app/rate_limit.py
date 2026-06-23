"""
Rate limiting backed by Upstash Redis instead of in-memory counters.

WHY: in-memory rate limiting (e.g. slowapi's default) only works
correctly when the same process handles repeated requests from the
same client. On a serverless platform like Vercel, each request can
land on a totally different, fresh function instance — an in-memory
counter would frequently reset to zero, silently defeating the whole
point of rate limiting. Upstash's Redis is HTTP-based (no persistent
connection needed) specifically so serverless functions can share
state cheaply between invocations.

If UPSTASH_REDIS_URL / UPSTASH_REDIS_TOKEN aren't set (e.g. local
development), rate limiting is skipped entirely rather than erroring —
acceptable for a single developer on their own machine, never
acceptable in production (enforced via settings.environment below).
"""
from fastapi import HTTPException, Request
from upstash_ratelimit import FixedWindow, Ratelimit
from upstash_redis import Redis

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("rate_limit")

_redis = None
if settings.upstash_redis_url and settings.upstash_redis_token:
    _redis = Redis(url=settings.upstash_redis_url, token=settings.upstash_redis_token)
else:
    logger.warning("Upstash Redis not configured — rate limiting is DISABLED. Fine for local dev, not for production.")


def _make_limiter(max_requests: int, window_seconds: int, prefix: str):
    if not _redis:
        return None
    return Ratelimit(redis=_redis, limiter=FixedWindow(max_requests=max_requests, window=window_seconds), prefix=prefix)


# Strict in production. Generous in development, since testing fires
# several signups in a row from the same machine/IP, and the limiter
# can't tell those are different phone numbers — it only sees "the
# same IP, too many requests."
_otp_request_limit = (3, 60) if settings.environment == "production" else (30, 60)
_otp_verify_limit = (10, 60) if settings.environment == "production" else (60, 60)

otp_request_limiter = _make_limiter(*_otp_request_limit, prefix="ratelimit:otp-request")
otp_verify_limiter = _make_limiter(*_otp_verify_limit, prefix="ratelimit:otp-verify")


def get_client_ip(request: Request) -> str:
    """
    Prefers X-Forwarded-For (set by Vercel's and most platforms' proxy
    layer to the real client IP) over request.client.host, which on a
    serverless platform often reflects the proxy, not the real caller.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(limiter, request: Request) -> None:
    """Call this inside an endpoint. Raises 429 if the caller's IP is over the limit."""
    if limiter is None:
        return  # not configured — e.g. local dev without Upstash credentials
    identifier = get_client_ip(request)
    result = limiter.limit(identifier)
    if not result.allowed:
        raise HTTPException(status_code=429, detail="Too many requests — please wait a moment and try again.")
