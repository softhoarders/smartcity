import os

# ---------------------------------------------------------------------------
# Server connection
# ---------------------------------------------------------------------------
SERVER_URL = os.environ.get("PARKWATCH_SERVER", "http://localhost:2026")

# ---------------------------------------------------------------------------
# Client health endpoint
# ---------------------------------------------------------------------------
CLIENT_PORT = int(os.environ.get("PARKWATCH_CLIENT_PORT", "3000"))

# ---------------------------------------------------------------------------
# Camera settings (720p capture, downscale for OCR)
# ---------------------------------------------------------------------------
CAMERA_INDEX = int(os.environ.get("PARKWATCH_CAMERA", "0"))
CAPTURE_WIDTH = int(os.environ.get("PARKWATCH_CAPTURE_WIDTH", "1280"))
CAPTURE_HEIGHT = int(os.environ.get("PARKWATCH_CAPTURE_HEIGHT", "720"))
CAMERA_WARMUP_FRAMES = int(os.environ.get("PARKWATCH_CAMERA_WARMUP", "3"))

# ---------------------------------------------------------------------------
# Scheduling (seconds) — default ~12 min day / 20 min night (10–15 min target)
# ---------------------------------------------------------------------------
DAY_INTERVAL = int(os.environ.get("PARKWATCH_DAY_INTERVAL", "720"))
NIGHT_INTERVAL = int(os.environ.get("PARKWATCH_NIGHT_INTERVAL", "1200"))
DAY_START_HOUR = int(os.environ.get("PARKWATCH_DAY_START", "6"))
DAY_END_HOUR = int(os.environ.get("PARKWATCH_DAY_END", "22"))

# ---------------------------------------------------------------------------
# Energy saving (DietPi / Raspberry Pi)
# ---------------------------------------------------------------------------
ENERGY_SAVE = os.environ.get("PARKWATCH_ENERGY_SAVE", "1").strip().lower() not in ("0", "false", "no")
SLEEP_CHUNK_SECONDS = int(os.environ.get("PARKWATCH_SLEEP_CHUNK", "45"))
WEATHER_POLL_CYCLES = int(os.environ.get("PARKWATCH_WEATHER_CYCLES", "48"))

# ---------------------------------------------------------------------------
# Plate reader settings
# ---------------------------------------------------------------------------
PROCESSING_MAX_WIDTH = int(os.environ.get("PARKWATCH_PROCESS_WIDTH", "960"))
TESSERACT_LANG = os.environ.get("PARKWATCH_TESS_LANG", "ron+eng")

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
CAPTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
os.makedirs(CAPTURE_DIR, exist_ok=True)

EVIDENCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence")
os.makedirs(EVIDENCE_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Test mode: static image instead of camera
# ---------------------------------------------------------------------------
TEST_IMAGE = os.environ.get("PARKWATCH_TEST_IMAGE", None)
