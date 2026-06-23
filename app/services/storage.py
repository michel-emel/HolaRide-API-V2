"""
Supabase Storage integration — used for vehicle photo uploads.

NOTE: this is the one part of the backend that talks to Supabase as a
platform rather than just "a Postgres database somewhere" — Storage
isn't a database table, it's a separate API. Needs SUPABASE_URL and
SUPABASE_SERVICE_ROLE_KEY in .env (different credentials than
DATABASE_URL — find both under Project Settings > API).
"""
import uuid

from supabase import create_client

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("storage")

_client = None
if settings.supabase_url and settings.supabase_service_role_key:
    _client = create_client(settings.supabase_url, settings.supabase_service_role_key)
else:
    logger.warning("Supabase Storage not configured — vehicle photo uploads will fail until SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set.")


def upload_vehicle_photo(vehicle_id, filename: str, content: bytes, content_type: str) -> str:
    """
    Uploads one photo to the vehicle-photos bucket and returns its
    public URL. Files are stored under <vehicle_id>/<random>-<filename>
    so multiple vehicles (and multiple photos per vehicle) never collide.
    """
    if not _client:
        raise RuntimeError(
            "Supabase Storage isn't configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY in .env before uploading photos."
        )

    path = f"{vehicle_id}/{uuid.uuid4().hex}-{filename}"
    bucket = _client.storage.from_(settings.supabase_vehicle_photos_bucket)
    bucket.upload(path, content, {"content-type": content_type})
    return bucket.get_public_url(path)
