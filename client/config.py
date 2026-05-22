import os

# ---------------------------------------------------------------------------
# Server connection
# ---------------------------------------------------------------------------
SERVER_URL = os.environ.get("PARKWATCH_SERVER", "http://localhost:2026")

# ---------------------------------------------------------------------------
# Client health endpoint
# ---------------------------------------------------------------------------
CLIENT_PORT = 3000

# ---------------------------------------------------------------------------
# Camera settings
# ---------------------------------------------------------------------------
CAMERA_INDEX = int(os.environ.get("PARKWATCH_CAMERA", "0"))
CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720

# ---------------------------------------------------------------------------
# Scheduling (seconds)
# ---------------------------------------------------------------------------
DAY_INTERVAL = 600       # 10 minutes
NIGHT_INTERVAL = 1800    # 30 minutes
DAY_START_HOUR = 6       # 06:00
DAY_END_HOUR = 22        # 22:00

# ---------------------------------------------------------------------------
# Plate reader settings
# ---------------------------------------------------------------------------
# Max width for image processing (resize to save memory on Pi Zero 2)
PROCESSING_MAX_WIDTH = 800

# Tesseract language (ron = Romanian, eng = English)
TESSERACT_LANG = "ron+eng"

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
CAPTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
os.makedirs(CAPTURE_DIR, exist_ok=True)

# Directory for storing fine evidence images locally
EVIDENCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence")
os.makedirs(EVIDENCE_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Test mode: use a static image instead of camera (for dev/testing)
# Set PARKWATCH_TEST_IMAGE=/path/to/image.jpg to enable
# ---------------------------------------------------------------------------
TEST_IMAGE = os.environ.get("PARKWATCH_TEST_IMAGE", None)
