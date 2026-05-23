import os

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

PORT = 2026
SECRET_KEY = os.environ.get("PARKWATCH_SECRET", "parkwatch-dev-key-change-in-production")
DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'parkwatch.db')}"

# Device is considered offline after this many seconds without heartbeat
OFFLINE_THRESHOLD_SECONDS = 120

# Upload folder for fine evidence images
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Admin credentials
ADMIN_USERNAME = os.environ.get("PARKWATCH_ADMIN_USER", "admin")
# "softhoarderscnfbmuzeu" hashed
ADMIN_PASSWORD_HASH = os.environ.get("PARKWATCH_ADMIN_HASH", "$2b$12$fT7VxwM7X./eF7CZZc0hQePBy3yVfD6hTfSMyD7hZzJLZ2Z2.Q2xG")
ADMIN_SIGNUP_CODE = os.environ.get("PARKWATCH_ADMIN_SIGNUP_CODE", "softhoarderscnfbmuzeu")

# Uploaded registration certificates, insurance cards, or vehicle ownership proof.
ALLOWED_PROOF_EXTENSIONS = {"png", "jpg", "jpeg", "pdf", "webp"}

# Plate registration documents (city hall / police / ownership certificate)
PLATE_PROOF_EXTENSIONS = {"pdf", "docx"}
PLATE_PROOF_MIME_TYPES = {
    "pdf": "application/pdf",
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

MOCK_MAIL_DIR = os.path.join(BASE_DIR, "mail_queue")
os.makedirs(MOCK_MAIL_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Spots wallet (1 Spot = 1 RON lei)
# ---------------------------------------------------------------------------
SPOT_TO_LEI = 1
SUBSCRIPTION_MONTHLY_LEI = int(os.environ.get("SPOTS_SUBSCRIPTION_LEI", "50"))
SUBSCRIPTION_MONTHLY_SPOTS = int(os.environ.get("SPOTS_SUBSCRIPTION_GRANT", "50"))
DEFAULT_INSTANT_PRICE_PER_HOUR = int(os.environ.get("SPOTS_INSTANT_HOURLY", "10"))
DEFAULT_SCHEDULE_DEPOSIT = int(os.environ.get("SPOTS_SCHEDULE_DEPOSIT", "5"))
DEFAULT_SCHEDULE_PRICE_PER_HOUR = int(os.environ.get("SPOTS_SCHEDULE_HOURLY", "8"))
MIN_INSTANT_HOURS = 1
MAX_BOOKING_HOURS = 72
NEW_USER_WELCOME_SPOTS = int(os.environ.get("SPOTS_WELCOME_BONUS", "0"))

# Smart pricing
BUCHAREST_CENTER_LAT = float(os.environ.get("BUCHAREST_CENTER_LAT", "44.4268"))
BUCHAREST_CENTER_LNG = float(os.environ.get("BUCHAREST_CENTER_LNG", "26.1025"))
PRICING_CENTRAL_KM = float(os.environ.get("PRICING_CENTRAL_KM", "2.5"))
PRICING_INNER_KM = float(os.environ.get("PRICING_INNER_KM", "8.0"))
PRICING_DEFAULT_MIN_TENTHS = int(os.environ.get("PRICING_MIN_TENTHS", "50"))
PRICING_DEFAULT_MAX_TENTHS = int(os.environ.get("PRICING_MAX_TENTHS", "300"))
PRICING_GEMINI_ENABLED = os.environ.get("PRICING_GEMINI_ENABLED", "true").lower() in ("true", "1", "t")
PRICING_REFRESH_INTERVAL_SECONDS = int(os.environ.get("PRICING_REFRESH_INTERVAL", "3600"))
GEO_CACHE_HOURS = int(os.environ.get("GEO_CACHE_HOURS", "24"))
NOMINATIM_USER_AGENT = os.environ.get("NOMINATIM_USER_AGENT", "Spotflow/1.0 (local dev)")
