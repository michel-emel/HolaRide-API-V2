from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All values come from your .env file. See .env.example for what's needed.
    """
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"  # "development" | "production"

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24        # 1 day
    refresh_token_expire_minutes: int = 60 * 24 * 30  # 30 days
    otp_expire_minutes: int = 5
    otp_dev_mode: bool = True

    # Lets a passenger skip real Mobile Money and instantly mark a
    # booking "paid" — for dev/testing only. Automatically disabled
    # when ENVIRONMENT=production regardless of .env.
    payment_dev_mode: bool = False

    # HR-Skills Pay — Mobile Money provider for Cameroon (MTN / Orange)
    hrskills_key_a: str = ""           # hrsk_pk_test_... or hrsk_pk_live_...
    hrskills_key_b: str = ""           # hrsk_sk_test_... or hrsk_sk_live_...
    hrskills_webhook_secret: str = ""  # from dashboard → Webhooks
    hrskills_sandbox: bool = False     # True = sandbox, False = live

    # Comma-separated list of allowed origins for browser-based clients.
    cors_allowed_origins: str = "http://localhost:3000"

    # Infobip — SMS provider for OTP delivery
    infobip_api_key: str = ""
    infobip_base_url: str = ""
    infobip_sender_id: str = "ServiceSMS"

    # Upstash Redis — rate limiting on serverless (Vercel)
    upstash_redis_url: str = ""
    upstash_redis_token: str = ""

    # Supabase — vehicle/document photo storage
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_vehicle_photos_bucket: str = "vehicle-photos"

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        """
        In production: OTP dev mode and payment dev mode are always off,
        regardless of what's in .env. Also: if live HR-Skills keys are
        present, sandbox mode can never silently stay on — prevents
        live keys being sent through the sandbox auth path (X-API-Secret
        instead of X-Transaction-Token), which HR-Skills rejects.
        """
        if self.environment == "production":
            if self.otp_dev_mode:
                self.otp_dev_mode = False
            if self.payment_dev_mode:
                self.payment_dev_mode = False

        if self.hrskills_sandbox and self.hrskills_key_a.startswith("hrsk_pk_live_"):
            self.hrskills_sandbox = False

        return self


settings = Settings()