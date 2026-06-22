import logging
import sys

from app.config import settings


def setup_logging() -> None:
    """
    Called once, at app startup (see main.py). Replaces scattered
    print() statements with real logging — meaning you get timestamps,
    severity levels, and the ability to send logs somewhere other than
    a terminal (a file, a log aggregator, etc.) later without touching
    any code that calls logger.info()/logger.warning()/etc.
    """
    level = logging.DEBUG if settings.environment == "development" else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    ))

    root = logging.getLogger("holaride")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"holaride.{name}")
