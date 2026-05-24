"""Vercel entrypoint — exposes the ParkWatch/Spotflow Flask app from server/."""

import importlib.util
import sys
from pathlib import Path

_SERVER_DIR = Path(__file__).resolve().parent / "server"
_SERVER_APP = _SERVER_DIR / "app.py"

if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

_spec = importlib.util.spec_from_file_location("spotflow_server_app", _SERVER_APP)
_module = importlib.util.module_from_spec(_spec)
sys.modules["spotflow_server_app"] = _module
_spec.loader.exec_module(_module)
app = _module.app
