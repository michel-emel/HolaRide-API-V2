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

    # Lets a passenger skip real Mobile Money entirely and instantly
    # mark a booking "paid" — mirrors quick_test.py's force_mark_paid(),
    # just reachable from the app itself for convenience while real
    # PawaPay integration is still being worked out. Defaults to False
    # (unlike otp_dev_mode, which defaults True) because accidentally
    # leaving a payment bypass on is a much bigger problem than an OTP
    # convenience. See _enforce_production_safety below — this can
    # never actually be active once ENVIRONMENT=production, regardless
    # of what's in .env.
    payment_dev_mode: bool = False

    # Comma-separated list of allowed origins for your Flutter web build
    # (if any) or any other browser-based client. Mobile apps calling
    # the API directly aren't affected by CORS at all.
    cors_allowed_origins: str = "http://localhost:3000"

    # PawaPay sandbox. NEVER commit a real token — this only ever comes
    # from your .env file. https://api.sandbox.pawapay.io for sandbox,
    # https://api.pawapay.io for production.
    pawapay_api_token: str = ""
    pawapay_base_url: str = "https://api.sandbox.pawapay.io"

    # Infobip — the only SMS provider this app uses, confirmed working
    # for MTN Cameroon via the dashboard's own test-send tool.
    # NEVER commit real values — .env file only.
    infobip_api_key: str = ""  # the part after "App " in your dashboard's Authorization header
    # Account-specific subdomain shown in your dashboard's code snippet,
    # e.g. "2yr9vp.api.infobip.com" — no "https://" prefix, that's added
    # automatically. Every Infobip account gets a different one of these.
    infobip_base_url: str = ""
    # On a trial account, Infobip silently substitutes ANY sender name
    # to "ServiceSMS" regardless of what's sent — confirmed directly
    # from your own dashboard test. Once you register a real sender ID
    # with Infobip for production, change this to that instead.
    infobip_sender_id: str = "ServiceSMS"

    # Upstash Redis — used for rate limiting on serverless platforms
    # (e.g. Vercel) where in-memory counters don't work, since each
    # request can hit a totally different function instance. If left
    # blank (e.g. local development), rate limiting is simply skipped
    # rather than erroring — fine for a single dev on their own machine.
    upstash_redis_url: str = ""
    upstash_redis_token: str = ""

    # Supabase — used for vehicle/document photo storage.
    # NEVER commit real values — .env file only.
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_vehicle_photos_bucket: str = "vehicle-photos"

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        """
        Safety net: even if someone forgets to flip OTP_DEV_MODE or
        PAYMENT_DEV_MODE in their production .env file, real OTPs
        always send for real and real Mobile Money payment is always
        required once ENVIRONMENT=production. Printing a real user's
        login code to a server log, or letting a booking skip payment
        entirely, would both be serious bugs in production — neither
        is just a convenience setting.
        """
        if self.environment == "production":
            if self.otp_dev_mode:
                self.otp_dev_mode = False
            if self.payment_dev_mode:
                self.payment_dev_mode = False
        return self


settings = Settings()