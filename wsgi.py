"""Vercel entrypoint — exposes the ParkWatch/Spotflow Flask app from server/."""

import sys
from pathlib import Path

_SERVER_DIR = Path(__file__).resolve().parent / "server"
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

from app import app  # noqa: F401
