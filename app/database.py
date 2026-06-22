from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# pool_pre_ping checks a connection is still alive before using it —
# avoids confusing errors if your local Postgres restarted.
engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# IMPORTANT: this Base is only used so SQLAlchemy knows how to map
# Python classes to your EXISTING tables. We never call
# Base.metadata.create_all() — your 001_schema.sql file is the one
# source of truth for the actual table structure, constraints, and
# indexes. This file just describes those tables to Python.
Base = declarative_base()


def get_db():
    """FastAPI dependency: gives each request its own DB session, closes it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
