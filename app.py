"""Vercel entrypoint — load the Spotflow Flask app from server/app.py."""

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SERVER = _ROOT / "server"
_SERVER_APP = _SERVER / "app.py"

if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

_spec = importlib.util.spec_from_file_location("spotflow_app", _SERVER_APP)
_module = importlib.util.module_from_spec(_spec)
sys.modules["spotflow_app"] = _module
_spec.loader.exec_module(_module)
app = _module.app
