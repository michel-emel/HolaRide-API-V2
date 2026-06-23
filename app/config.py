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
    access_token_expire_minutes: int = 60 * 24       # 1 day
    refresh_token_expire_minutes: int = 60 * 24 * 30  # 30 days
    otp_expire_minutes: int = 5
    otp_dev_mode: bool = True

    # Comma-separated list of allowed origins for your Flutter web build
    # (if any) or any other browser-based client. Mobile apps calling
    # the API directly aren't affected by CORS at all.
    cors_allowed_origins: str = "http://localhost:3000"

    # PawaPay sandbox. NEVER commit a real token — this only ever comes
    # from your .env file. https://api.sandbox.pawapay.io for sandbox,
    # https://api.pawapay.io for production.
    pawapay_api_token: str = ""
    pawapay_base_url: str = "https://api.sandbox.pawapay.io"

    # Twilio — used for real OTP delivery once OTP_DEV_MODE is false.
    # NEVER commit real values — .env file only.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""  # the Twilio number you were given/bought, e.g. +15017122661

    # Termii — alternative SMS provider, often better Cameroon coverage.
    # NEVER commit real values — .env file only.
    termii_api_key: str = ""
    termii_sender_id: str = ""  # your registered sender ID from the Termii dashboard
    # "dnd" is correct for OTP/transactional per Termii's own docs, but it
    # must be activated on your account first (contact Termii support).
    # If you haven't activated it yet, set this to "generic" temporarily —
    # Termii's docs warn generic risks delivery failures/blocked sender ID
    # for OTPs, so switch back to "dnd" as soon as it's enabled.
    termii_channel: str = "dnd"

    # Which provider actually sends the SMS: "twilio" or "termii"
    sms_provider: str = "termii"

    # Upstash Redis — used for rate limiting on serverless platforms
    # (e.g. Vercel) where in-memory counters don't work, since each
    # request can hit a totally different function instance. If left
    # blank (e.g. local development), rate limiting is simply skipped
    # rather than erroring — fine for a single dev on their own machine.
    upstash_redis_url: str = ""
    upstash_redis_token: str = ""

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        """
        Safety net: even if someone forgets to flip OTP_DEV_MODE in
        their production .env file, real OTPs always send for real
        once ENVIRONMENT=production. Printing a real user's login
        code to a server log in production would be a serious
        security bug, not just a convenience setting.
        """
        if self.environment == "production" and self.otp_dev_mode:
            self.otp_dev_mode = False
        return self


settings = Settings()
