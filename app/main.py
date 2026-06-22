import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.logging_config import get_logger, setup_logging
from app.rate_limit import limiter
from app.routers import admin, auth, bookings, chat, drivers, location, payments, reviews, trips, users

setup_logging()
logger = get_logger("main")

app = FastAPI(title="HolaRide API")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Every validation failure (bad phone format, missing field, etc.) comes back
    in one consistent shape, instead of FastAPI's default verbose format."""
    cleaned_errors = []
    for err in exc.errors():
        err = dict(err)
        # 'ctx' can contain the raw Python exception object from a custom
        # validator (e.g. our phone number check) — not JSON-serializable,
        # and the human-readable message is already in 'msg' anyway.
        err.pop("ctx", None)
        cleaned_errors.append(err)
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": cleaned_errors},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Same consistent shape for the HTTPException(...) calls used throughout the routers."""
    return JSONResponse(status_code=exc.status_code, content={"error": "request_error", "detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Catches anything NOT already handled above — a bug, a database
    hiccup, anything unexpected. Logs the full details on the server
    so you can debug it, but never leaks a stack trace to the client.
    That distinction matters: in dev you want to see everything; in
    production, a leaked stack trace can expose internals to an attacker.
    """
    logger.exception(f"Unhandled error on {request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": "Something went wrong on our end."},
    )


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(drivers.router)
app.include_router(trips.router)
app.include_router(bookings.router)
app.include_router(bookings.actions_router)
app.include_router(payments.router)
app.include_router(admin.router)
app.include_router(chat.router)
app.include_router(location.router)
app.include_router(reviews.router)


@app.get("/health")
def health():
    """Checks the database connection too, not just that the process is alive —
    a server that's 'up' but can't reach Postgres should NOT report healthy."""
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        db_status = "connected"
    except Exception as exc:
        logger.error(f"Health check DB connection failed: {exc}")
        db_status = "unreachable"

    return {"status": "ok" if db_status == "connected" else "degraded", "database": db_status}
