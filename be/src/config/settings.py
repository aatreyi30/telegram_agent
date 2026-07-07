"""Runtime configuration — the single source of truth for all settings.

Every value is env-driven (see ``.env.example``). Pure-Python (dotenv +
dataclass) so it installs cleanly on any interpreter without compiled deps.

Per Global Rule 2 (DATA FIRST), a collector whose credentials/config are
missing must report itself UNAVAILABLE rather than fabricate data. The
``*_available`` helpers below let each collector make that decision explicitly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _get(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _get_int(name: str, default: int) -> int:
    raw = _get(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = _get(name)
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default


@dataclass
class Settings:
    # --- Runtime / server (template contract) ---
    environment: str = "development"     # development | production | test
    port: int = 8000
    cors_origin: str = "http://localhost:5173"   # the frontend dev origin
    # auto-start the 20-job scheduler registry on server boot (cron runs automatically)
    schedulers_autostart: bool = False

    # --- Storage ---
    db_url: str = "sqlite:///./data/tgagent.db"
    raw_snapshot_dir: Path = field(default_factory=lambda: Path("./data/raw_snapshots"))

    # --- Telegram MTProto (owned channels) ---
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session_name: str = "tg_owned_session"
    telegram_phone: str | None = None
    owned_channels_raw: str | None = None

    # --- Competitor monitoring (t.me/s) ---
    competitor_channels_raw: str | None = None
    tme_request_delay_seconds: float = 2.0
    tme_user_agent: str = "Mozilla/5.0 (compatible; TGIntelBot/1.0)"

    # --- Merchant enrichment (buildable merchants only) ---
    amazon_associate_tag: str | None = None
    amazon_creators_access_key: str | None = None
    amazon_creators_secret_key: str | None = None
    amazon_marketplace: str = "www.amazon.in"
    flipkart_affiliate_id: str | None = None
    flipkart_affiliate_token: str | None = None

    # --- Affiliate link tracking ---
    link_shortener_base: str | None = None

    # --- Affiliate link GENERATION (multi-provider; org-selected) ---
    # Which provider transforms product URLs into affiliate/tracked links.
    # "grabon" activates GrabOn's client-specific rules + shortener; anything
    # else (or unset) uses the generic pass-through provider. NO provider-
    # specific logic lives in the core — see tgagent/affiliate/.
    affiliate_provider: str | None = None
    grabon_shortener_url: str = "https://shortner-api.grabon.com/api/url/shorten"
    grabon_amazon_tag: str = "tlg022-21"
    grabon_flipkart_params: str = "affid=bh7162&affExtParam1=1005&affExtParam2=gb"
    # shorten EVERY link (even merchants with no affiliate rule) so output matches how the
    # channel actually posts (all links are grbn.in). Fallback still never blocks posting.
    grabon_shorten_all: bool = True

    # --- Organization (multi-tenant; the seeded default org) ---
    org_key: str = "grabon"
    org_name: str = "GrabOn"

    # --- Auth (dashboard login) ---
    auth_secret: str | None = None          # HMAC signing key (falls back to api_secret_key)
    admin_email: str = "admin@dealwing.local"
    admin_password: str | None = None        # seed password; if unset a random one is printed once

    # --- Deal source (GrabCash API or similar) — captured for later wiring ---
    api_secret_key: str | None = None
    grabcash_api_base: str | None = None

    # --- Scheduler cadence ---
    owned_incremental_interval_min: int = 15
    owned_analytics_interval_min: int = 60
    competitor_interval_min: int = 60
    merchant_refresh_interval_min: int = 360
    link_resolve_interval_min: int = 60
    metric_snapshot_offsets_raw: str = "1,4,24"

    # --- AI layer (Groq — OpenAI-compatible) ---
    groq_api_key: str | None = None
    anthropic_api_key: str | None = None  # optional alternative provider
    ai_model: str = "llama-3.3-70b-versatile"

    # --- Runtime ---
    log_level: str = "INFO"

    # ------------------------------------------------------------------ #
    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()  # loads .env if present; real env vars take precedence
        api_id_raw = _get("TELEGRAM_API_ID")
        return cls(
            environment=_get("ENVIRONMENT", "development"),
            port=_get_int("PORT", 8000),
            cors_origin=_get("CORS_ORIGIN", "http://localhost:5173"),
            schedulers_autostart=_get("SCHEDULERS_AUTOSTART", "false").lower() in ("1", "true", "yes"),
            db_url=_get("DB_URL", "sqlite:///./data/tgagent.db"),
            raw_snapshot_dir=Path(_get("RAW_SNAPSHOT_DIR", "./data/raw_snapshots")),
            telegram_api_id=int(api_id_raw) if api_id_raw and api_id_raw.isdigit() else None,
            telegram_api_hash=_get("TELEGRAM_API_HASH"),
            # accept TELEGRAM_SESSION_NAME or the shorter TELETHON_SESSION
            telegram_session_name=_get("TELEGRAM_SESSION_NAME")
            or _get("TELETHON_SESSION", "tg_owned_session"),
            telegram_phone=_get("TELEGRAM_PHONE") or _get("PHONE_NUMBER"),
            owned_channels_raw=_get("OWNED_CHANNELS"),
            competitor_channels_raw=_get("COMPETITOR_CHANNELS"),
            tme_request_delay_seconds=_get_float("TME_REQUEST_DELAY_SECONDS", 2.0),
            tme_user_agent=_get("TME_USER_AGENT", "Mozilla/5.0 (compatible; TGIntelBot/1.0)"),
            amazon_associate_tag=_get("AMAZON_ASSOCIATE_TAG"),
            amazon_creators_access_key=_get("AMAZON_CREATORS_ACCESS_KEY"),
            amazon_creators_secret_key=_get("AMAZON_CREATORS_SECRET_KEY"),
            amazon_marketplace=_get("AMAZON_MARKETPLACE", "www.amazon.in"),
            flipkart_affiliate_id=_get("FLIPKART_AFFILIATE_ID"),
            flipkart_affiliate_token=_get("FLIPKART_AFFILIATE_TOKEN"),
            link_shortener_base=_get("LINK_SHORTENER_BASE"),
            affiliate_provider=_get("AFFILIATE_PROVIDER"),
            grabon_shortener_url=_get("GRABON_SHORTENER_URL",
                                      "https://shortner-api.grabon.com/api/url/shorten"),
            grabon_amazon_tag=_get("GRABON_AMAZON_TAG", "tlg022-21"),
            grabon_flipkart_params=_get("GRABON_FLIPKART_PARAMS",
                                        "affid=bh7162&affExtParam1=1005&affExtParam2=gb"),
            grabon_shorten_all=_get("GRABON_SHORTEN_ALL", "true").lower() in ("1", "true", "yes"),
            org_key=_get("ORG_KEY", "grabon"),
            org_name=_get("ORG_NAME", "GrabOn"),
            auth_secret=_get("AUTH_SECRET"),
            admin_email=_get("ADMIN_EMAIL", "admin@dealwing.local"),
            admin_password=_get("ADMIN_PASSWORD"),
            api_secret_key=_get("API_SECRET_KEY"),
            grabcash_api_base=_get("GRABCASH_API_BASE"),
            groq_api_key=_get("GROQ_API_KEY"),
            anthropic_api_key=_get("ANTHROPIC_API_KEY"),
            ai_model=_get("AI_MODEL", "llama-3.3-70b-versatile"),
            owned_incremental_interval_min=_get_int("OWNED_INCREMENTAL_INTERVAL_MIN", 15),
            owned_analytics_interval_min=_get_int("OWNED_ANALYTICS_INTERVAL_MIN", 60),
            competitor_interval_min=_get_int("COMPETITOR_INTERVAL_MIN", 60),
            merchant_refresh_interval_min=_get_int("MERCHANT_REFRESH_INTERVAL_MIN", 360),
            link_resolve_interval_min=_get_int("LINK_RESOLVE_INTERVAL_MIN", 60),
            metric_snapshot_offsets_raw=_get("METRIC_SNAPSHOT_OFFSETS_HOURS", "1,4,24"),
            log_level=_get("LOG_LEVEL", "INFO"),
        )

    # ------------------------------------------------------------------ #
    # Derived accessors
    # ------------------------------------------------------------------ #
    @property
    def owned_channels(self) -> list[str]:
        return _split_csv(self.owned_channels_raw)

    @property
    def competitor_channels(self) -> list[str]:
        return _split_csv(self.competitor_channels_raw)

    @property
    def metric_snapshot_offsets_hours(self) -> list[int]:
        return [int(x) for x in _split_csv(self.metric_snapshot_offsets_raw)]

    @property
    def telegram_available(self) -> bool:
        return bool(self.telegram_api_id and self.telegram_api_hash and self.owned_channels)

    @property
    def competitors_available(self) -> bool:
        return bool(self.competitor_channels)

    @property
    def amazon_available(self) -> bool:
        return bool(
            self.amazon_associate_tag
            and self.amazon_creators_access_key
            and self.amazon_creators_secret_key
        )

    @property
    def flipkart_available(self) -> bool:
        return bool(self.flipkart_affiliate_id and self.flipkart_affiliate_token)

    @property
    def ai_available(self) -> bool:
        return bool(self.groq_api_key or self.anthropic_api_key)

    @property
    def affiliate_provider_name(self) -> str:
        """Normalised provider key; 'generic' when unset."""
        return (self.affiliate_provider or "generic").strip().lower()

    def ensure_dirs(self) -> None:
        self.raw_snapshot_dir.mkdir(parents=True, exist_ok=True)
        if self.db_url.startswith("sqlite"):
            db_path = self.db_url.split("///", 1)[-1]
            parent = Path(db_path).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
