import json
import os

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

IS_VERCEL = os.environ.get("VERCEL") == "1" or bool(os.environ.get("VERCEL_ENV"))
# Serverless filesystem is read-only except /tmp; keep DB and uploads there on Vercel.
DATA_DIR = os.path.join("/tmp", "spotflow") if IS_VERCEL else BASE_DIR
if IS_VERCEL:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except OSError:
        pass

PORT = 2026
SECRET_KEY = os.environ.get("PARKWATCH_SECRET", "parkwatch-dev-key-change-in-production")
DATABASE_URI = f"sqlite:///{os.path.join(DATA_DIR, 'parkwatch.db')}"

# Device is considered offline after this many seconds without heartbeat
OFFLINE_THRESHOLD_SECONDS = 120

# Upload folder for fine evidence images
UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except OSError:
    pass

# Admin credentials
ADMIN_USERNAME = os.environ.get("PARKWATCH_ADMIN_USER", "admin")
# "softhoarderscnfbmuzeu" hashed
ADMIN_PASSWORD_HASH = os.environ.get("PARKWATCH_ADMIN_HASH", "$2b$12$fT7VxwM7X./eF7CZZc0hQePBy3yVfD6hTfSMyD7hZzJLZ2Z2.Q2xG")
ADMIN_SIGNUP_CODE = os.environ.get("PARKWATCH_ADMIN_SIGNUP_CODE", "softhoarderscnfbmuzeu")

# Uploaded registration certificates, insurance cards, or vehicle ownership proof.
ALLOWED_PROOF_EXTENSIONS = {"png", "jpg", "jpeg", "pdf", "webp"}

# Plate registration documents (city hall / police / ownership certificate)
PLATE_PROOF_EXTENSIONS = {"pdf", "doc", "docx"}
PLATE_PROOF_MIME_TYPES = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_PLATE_PROOF_BYTES = 8 * 1024 * 1024

# Google Gemini — document verification for new plates
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Mail configuration
MAIL_SERVER = os.environ.get("MAIL_SERVER", "localhost")
MAIL_PORT = int(os.environ.get("MAIL_PORT", "1025"))
MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "False").lower() in ("true", "1", "t")
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@spotflow.com")

MOCK_MAIL_DIR = os.path.join(DATA_DIR, "mail_queue")
try:
    os.makedirs(MOCK_MAIL_DIR, exist_ok=True)
except OSError:
    pass

# ---------------------------------------------------------------------------
# Wallet credits (1 Credit = 1 RON lei). DB columns remain spots_* for compatibility.
# ---------------------------------------------------------------------------
WALLET_CURRENCY_NAME = os.environ.get("WALLET_CURRENCY_NAME", "Credits")
WALLET_CURRENCY_SINGULAR = os.environ.get("WALLET_CURRENCY_SINGULAR", "Credit")
SPOT_TO_LEI = 1
SUBSCRIPTION_MONTHLY_LEI = int(os.environ.get("SPOTS_SUBSCRIPTION_LEI", "50"))
SUBSCRIPTION_MONTHLY_SPOTS = int(os.environ.get("SPOTS_SUBSCRIPTION_GRANT", "50"))
DEFAULT_INSTANT_PRICE_PER_HOUR = int(os.environ.get("SPOTS_INSTANT_HOURLY", "4"))
DEFAULT_SCHEDULE_DEPOSIT = int(os.environ.get("SPOTS_SCHEDULE_DEPOSIT", "3"))
DEFAULT_SCHEDULE_PRICE_PER_HOUR = int(os.environ.get("SPOTS_SCHEDULE_HOURLY", "3"))
MAX_LISTING_PRICE_HUNDREDTHS = int(os.environ.get("MAX_LISTING_PRICE_HUNDREDTHS", "500"))
MIN_INSTANT_HOURS = 1
MAX_BOOKING_HOURS = 72
NEW_USER_WELCOME_SPOTS = int(os.environ.get("SPOTS_WELCOME_BONUS", "0"))

# Low balance warning (wallet hundredths; 1000 = 10.00 Credits)
LOW_BALANCE_THRESHOLD = int(os.environ.get("LOW_BALANCE_THRESHOLD", "1000"))

# Find parking: default search radius (~2 miles)
FIND_PARKING_RADIUS_KM = float(os.environ.get("FIND_PARKING_RADIUS_KM", "12"))

# Bank withdrawal: fixed bundle
WITHDRAWAL_CREDITS = int(os.environ.get("WITHDRAWAL_CREDITS", "100"))
WITHDRAWAL_LEI = int(os.environ.get("WITHDRAWAL_LEI", "100"))

# Promo / referral defaults
REFERRAL_BONUS_REFERRER = int(os.environ.get("REFERRAL_BONUS_REFERRER", "25"))
REFERRAL_BONUS_REFEREE = int(os.environ.get("REFERRAL_BONUS_REFEREE", "10"))
DEFAULT_PROMO_TOPUP_PERCENT = int(os.environ.get("DEFAULT_PROMO_TOPUP_PERCENT", "10"))

# Smart pricing
BUCHAREST_CENTER_LAT = float(os.environ.get("BUCHAREST_CENTER_LAT", "44.4268"))
BUCHAREST_CENTER_LNG = float(os.environ.get("BUCHAREST_CENTER_LNG", "26.1025"))
PRICING_CENTRAL_KM = float(os.environ.get("PRICING_CENTRAL_KM", "2.5"))
PRICING_INNER_KM = float(os.environ.get("PRICING_INNER_KM", "8.0"))
PRICING_DEFAULT_MIN_TENTHS = int(os.environ.get("PRICING_MIN_TENTHS", "300"))
PRICING_DEFAULT_MAX_TENTHS = int(os.environ.get("PRICING_MAX_TENTHS", "500"))
PRICING_GEMINI_ENABLED = os.environ.get("PRICING_GEMINI_ENABLED", "true").lower() in ("true", "1", "t")
PRICING_REFRESH_INTERVAL_SECONDS = int(os.environ.get("PRICING_REFRESH_INTERVAL", "3600"))
GEO_CACHE_HOURS = int(os.environ.get("GEO_CACHE_HOURS", "24"))
NOMINATIM_USER_AGENT = os.environ.get("NOMINATIM_USER_AGENT", "Spotflow/1.0 (local dev)")

# Public URL for photo links in n8n webhooks (e.g. https://park.example.com)
PUBLIC_BASE_URL = os.environ.get("SPOTFLOW_PUBLIC_URL", "").rstrip("/")

# ---------------------------------------------------------------------------
# n8n automation
# ---------------------------------------------------------------------------
N8N_ENABLED = os.environ.get("N8N_ENABLED", "false").lower() in ("true", "1", "t")
# Single webhook base, e.g. http://localhost:5678/webhook
N8N_WEBHOOK_BASE_URL = os.environ.get("N8N_WEBHOOK_BASE_URL", "")
N8N_WEBHOOK_SECRET = os.environ.get("N8N_WEBHOOK_SECRET", "")
N8N_WEBHOOK_API_KEY = os.environ.get("N8N_WEBHOOK_API_KEY", "")
# Inbound API key for n8n → Spotflow calls (header X-Spotflow-Api-Key)
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")
# Optional per-event override URLs (JSON object in env)
_n8n_urls_raw = os.environ.get("N8N_WEBHOOK_URLS", "")
try:
    N8N_WEBHOOK_URLS = json.loads(_n8n_urls_raw) if _n8n_urls_raw else {}
except json.JSONDecodeError:
    N8N_WEBHOOK_URLS = {}

# Edge device API (Pi) — optional shared secret
DEVICE_API_KEY = os.environ.get("DEVICE_API_KEY", "")

# Security
FORCE_HTTPS = IS_VERCEL or os.environ.get("SPOTFLOW_FORCE_HTTPS", "false").lower() in (
    "true",
    "1",
    "t",
)
RATE_LIMIT_DEFAULT = int(os.environ.get("RATE_LIMIT_DEFAULT", "120"))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_LOGIN_ATTEMPTS = int(os.environ.get("RATE_LIMIT_LOGIN_ATTEMPTS", "8"))
RATE_LIMIT_LOGIN_WINDOW = int(os.environ.get("RATE_LIMIT_LOGIN_WINDOW", "900"))

# Concierge + predictive availability
CONCIERGE_ENABLED = os.environ.get("CONCIERGE_ENABLED", "true").lower() in ("true", "1", "t")
CONCIERGE_MODEL = os.environ.get("CONCIERGE_MODEL", "") or GEMINI_MODEL
WAITLIST_DEFAULT_AUTO_BOOK = os.environ.get("WAITLIST_DEFAULT_AUTO_BOOK", "true").lower() in ("true", "1", "t")
WAITLIST_MAX_ACTIVE_PER_USER = int(os.environ.get("WAITLIST_MAX_ACTIVE_PER_USER", "5"))
WAITLIST_GRACE_MINUTES = int(os.environ.get("WAITLIST_GRACE_MINUTES", "15"))
AVAILABILITY_HISTORY_DAYS = int(os.environ.get("AVAILABILITY_HISTORY_DAYS", "30"))

# Flow routing (park nearby + walk)
ROUTING_DIRECT_MAX_KM = float(os.environ.get("ROUTING_DIRECT_MAX_KM", "0.35"))
ROUTING_WALK_SPEED_KMH = float(os.environ.get("ROUTING_WALK_SPEED_KMH", "4.8"))
ROUTING_RECOMMEND_DIRECT = int(os.environ.get("ROUTING_RECOMMEND_DIRECT", "2"))
ROUTING_RECOMMEND_FLOW = int(os.environ.get("ROUTING_RECOMMEND_FLOW", "2"))
ROUTING_RECOMMEND_TOTAL = int(os.environ.get("ROUTING_RECOMMEND_TOTAL", "4"))
ROUTING_CONCIERGE_DIRECT = int(os.environ.get("ROUTING_CONCIERGE_DIRECT", "2"))
ROUTING_CONCIERGE_FLOW = int(os.environ.get("ROUTING_CONCIERGE_FLOW", "1"))
ROUTING_CONCIERGE_TOTAL = int(os.environ.get("ROUTING_CONCIERGE_TOTAL", "3"))

# Parking reputation passport
REPUTATION_DEFAULT_NEW_SCORE = int(os.environ.get("REPUTATION_DEFAULT_NEW_SCORE", "55"))
REPUTATION_MIN_AUTO_BOOK = int(os.environ.get("REPUTATION_MIN_AUTO_BOOK", "45"))
REPUTATION_BLOCK_BELOW = int(os.environ.get("REPUTATION_BLOCK_BELOW", "25"))
REPUTATION_TIER_FLAGGED_MAX = int(os.environ.get("REPUTATION_TIER_FLAGGED_MAX", "30"))
REPUTATION_TIER_RESTRICTED_MAX = int(os.environ.get("REPUTATION_TIER_RESTRICTED_MAX", "45"))
REPUTATION_TIER_GOOD_MAX = int(os.environ.get("REPUTATION_TIER_GOOD_MAX", "65"))
REPUTATION_TIER_TRUSTED_MAX = int(os.environ.get("REPUTATION_TIER_TRUSTED_MAX", "80"))
REPUTATION_TIER_EXCELLENT_MAX = int(os.environ.get("REPUTATION_TIER_EXCELLENT_MAX", "90"))

# Simulated 2FA — show current code on verify page (always simulated, never real SMS)
SIMULATED_2FA_SHOW_CODE = os.environ.get("SIMULATED_2FA_SHOW_CODE", "true").lower() in ("true", "1", "t")
# Fixed mock code for login email verification (no real email sent)
MOCK_LOGIN_2FA_PIN = os.environ.get("MOCK_LOGIN_2FA_PIN", "456789")
