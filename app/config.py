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
    access_token_expire_minutes: int = 60 * 24
    refresh_token_expire_minutes: int = 60 * 24 * 30
    otp_expire_minutes: int = 5
    otp_dev_mode: bool = True

    cors_allowed_origins: str = "http://localhost:3000"

    pawapay_api_token: str = ""
    pawapay_base_url: str = "https://api.sandbox.pawapay.io"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    termii_api_key: str = ""
    termii_sender_id: str = ""
    termii_channel: str = "dnd"
    sms_provider: str = "termii"

    upstash_redis_url: str = ""
    upstash_redis_token: str = ""

    # Supabase — used for vehicle/document photo storage.
    # NEVER commit real values — .env file only.
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        if self.environment == "production" and self.otp_dev_mode:
            self.otp_dev_mode = False
        return self

settings = Settings()
