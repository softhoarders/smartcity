import os

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

PORT = 2026
SECRET_KEY = os.environ.get("PARKWATCH_SECRET", "parkwatch-dev-key-change-in-production")
DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'parkwatch.db')}"

# Device is considered offline after this many seconds without heartbeat
OFFLINE_THRESHOLD_SECONDS = 120

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
# Google AI Studio model ID (e.g. gemini-2.5-flash). Override with GEMINI_MODEL if you use another flash variant.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Mail configuration
MAIL_SERVER = os.environ.get("MAIL_SERVER", "localhost")
MAIL_PORT = int(os.environ.get("MAIL_PORT", "1025"))
MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "False").lower() in ("true", "1", "t")
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@parkscan.com")

MOCK_MAIL_DIR = os.path.join(BASE_DIR, "mail_queue")
os.makedirs(MOCK_MAIL_DIR, exist_ok=True)
