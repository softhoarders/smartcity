import os
import re
import uuid
import hmac
import shlex
import secrets
import subprocess
import pty
import fcntl
import select
import signal
from datetime import datetime, timezone, timedelta

from flask import (Flask, request, jsonify, render_template,
                   redirect, url_for, flash, send_from_directory, abort, Response, session)
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
from sqlalchemy import inspect, text
from functools import wraps
import queue
import threading
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
import config
from models import db, Device, Fine, User, UserPlate, PushSubscription, FineMessage
from mailer import mail, PhotoMailerWorker
from plate_document_verifier import verify_plate_registration_document, normalize_plate_for_claim
import json
from pywebpush import webpush, WebPushException

# VAPID Config
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_CLAIMS = {
    "sub": os.getenv("VAPID_SUBJECT", "mailto:admin@parkscan.com")
}

TERMINAL_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "terminal_config.yaml")
TERMINAL_SESSIONS = {}
TERMINAL_LOCK = threading.Lock()
PROTECTED_PATHS = (
    "/System", "/Library", "/bin", "/sbin", "/usr", "/etc", "/var", "/private/etc",
    "/private/var", "/Applications", "/dev", "/Volumes",
)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = config.DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER

app.config["MAIL_SERVER"] = config.MAIL_SERVER
app.config["MAIL_PORT"] = config.MAIL_PORT
app.config["MAIL_USE_TLS"] = config.MAIL_USE_TLS
app.config["MAIL_USERNAME"] = config.MAIL_USERNAME
app.config["MAIL_PASSWORD"] = config.MAIL_PASSWORD
app.config["MAIL_DEFAULT_SENDER"] = config.MAIL_DEFAULT_SENDER

CORS(app)
db.init_app(app)
bcrypt = Bcrypt(app)
mail.init_app(app)

@app.context_processor
def inject_globals():
    return {}

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

with app.app_context():
    db.create_all()

    inspector = inspect(db.engine)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    user_column_defaults = {
        "role": "VARCHAR(20) NOT NULL DEFAULT 'driver'",
        "verification_status": "VARCHAR(20) NOT NULL DEFAULT 'approved'",
        "verification_document": "VARCHAR(255)",
        "verification_notes": "VARCHAR(500)",
    }
    for column_name, column_sql in user_column_defaults.items():
        if column_name not in user_columns:
            db.session.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_sql}"))

    device_columns = {column["name"] for column in inspector.get_columns("devices")}
    device_column_defaults = {
        "latitude": "FLOAT",
        "longitude": "FLOAT",
        "notes": "TEXT",
    }
    for column_name, column_sql in device_column_defaults.items():
        if column_name not in device_columns:
            db.session.execute(text(f"ALTER TABLE devices ADD COLUMN {column_name} {column_sql}"))

    plate_columns = {column["name"] for column in inspector.get_columns("user_plates")}
    plate_column_defaults = {
        "verification_status": "VARCHAR(20) NOT NULL DEFAULT 'approved'",
        "verification_document": "VARCHAR(255)",
        "verification_notes": "VARCHAR(500)",
        "verified_at": "DATETIME",
    }
    for column_name, column_sql in plate_column_defaults.items():
        if column_name not in plate_columns:
            db.session.execute(text(f"ALTER TABLE user_plates ADD COLUMN {column_name} {column_sql}"))

    db.session.commit()

# Start background mailer worker
mailer_worker = PhotoMailerWorker(app)
mailer_worker.start()

def cleanup_old_files():
    cutoff = datetime.now() - timedelta(days=30)
    for root, _, files in os.walk(app.config["UPLOAD_FOLDER"]):
        for f in files:
            p = os.path.join(root, f)
            if datetime.fromtimestamp(os.path.getctime(p)) < cutoff:
                try: os.remove(p)
                except: pass

def periodic_cleanup():
    while True:
        cleanup_old_files()
        import time
        time.sleep(86400) # Once a day

threading.Thread(target=periodic_cleanup, daemon=True).start()

# ---------------------------------------------------------------------------
# Auth Helpers
# ---------------------------------------------------------------------------

@login_manager.user_loader
def load_user(user_id):
    if user_id == "0":
        admin_user = User(email="admin", password_hash="", license_plate="", role="admin", verification_status="approved")
        admin_user.id = 0
        admin_user.name = "Admin"
        return admin_user
    if user_id == "-1":
        demo_admin = User(email="demo", password_hash="", license_plate="", role="admin", verification_status="approved")
        demo_admin.id = -1
        demo_admin.name = "Demo Admin"
        return demo_admin
    if user_id == "-2":
        demo_user = User(email="demo", password_hash="", license_plate="B-123-MAB", role="driver", verification_status="approved")
        demo_user.id = -2
        demo_user.name = "Demo User"
        demo_user.plate_list = ["B123MAB"]
        return demo_user
    return User.query.get(int(user_id))

def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Admin access required.", "danger")
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def _parse_scalar(value):
    value = value.strip()
    lower = value.lower()
    if lower in {"true", "yes", "on"}:
        return True
    if lower in {"false", "no", "off"}:
        return False
    if lower in {"null", "none", "~"}:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value

def load_terminal_config():
    cfg = {
        "enabled": True,
        "username": "admin",
        "password": "admin123!",
        "loopback_only": True,
        "working_directory": ".",
        "command_timeout_seconds": 8,
        "max_output_chars": 20000,
        "blocked_commands": [
            "rm", "rmdir", "mv", "dd", "mkfs", "shutdown", "reboot",
            "halt", "poweroff", "sudo", "su", "chmod", "chown",
            "kill", "pkill", "killall", "systemctl", "service",
            "launchctl", "diskutil", "unlink", "trash", "sh", "bash",
            "zsh", "fish", "csh", "tcsh", "ksh", "dash", "python",
            "python3", "perl", "ruby", "node",
        ],
        "protected_paths": list(PROTECTED_PATHS),
    }

    if not os.path.exists(TERMINAL_CONFIG_PATH):
        return cfg

    current_key = None
    with open(TERMINAL_CONFIG_PATH, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            if line.startswith((" ", "\t")) and current_key:
                item = line.strip()
                if item.startswith("- "):
                    cfg.setdefault(current_key, [])
                    if not isinstance(cfg[current_key], list):
                        cfg[current_key] = []
                    cfg[current_key].append(_parse_scalar(item[2:]))
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            current_key = key
            if value == "":
                cfg[key] = []
            else:
                cfg[key] = _parse_scalar(value)

    return cfg

def _terminal_remote_allowed(cfg):
    if not cfg.get("loopback_only", True):
        return True
    return request.remote_addr in {"127.0.0.1", "::1", "localhost"}

def _terminal_cwd(cfg):
    configured = str(cfg.get("working_directory") or ".")
    if os.path.isabs(configured):
        cwd = configured
    else:
        cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), configured))
    server_root = os.path.abspath(os.path.dirname(__file__))
    if not os.path.isdir(cwd) or os.path.commonpath([server_root, cwd]) != server_root:
        return server_root
    return cwd

def require_terminal_login(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        cfg = load_terminal_config()
        if not cfg.get("enabled", True):
            abort(404)
        if not _terminal_remote_allowed(cfg):
            abort(403)
        if not session.get("terminal_admin"):
            return redirect(url_for("terminal_login"))
        return f(*args, **kwargs)
    return decorated_function

def _terminal_csrf_token():
    token = session.get("terminal_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["terminal_csrf"] = token
    return token

def _valid_terminal_csrf():
    token = session.get("terminal_csrf", "")
    posted = request.form.get("csrf_token", "")
    return bool(token and posted and hmac.compare_digest(token, posted))

def _terminal_sid():
    sid = session.get("terminal_sid")
    if not sid:
        sid = secrets.token_urlsafe(24)
        session["terminal_sid"] = sid
    return sid

def _close_terminal_session(sid):
    with TERMINAL_LOCK:
        term = TERMINAL_SESSIONS.pop(sid, None)
    if not term:
        return
    proc = term.get("process")
    master_fd = term.get("master_fd")
    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGHUP)
        except Exception:
            pass
    if master_fd is not None:
        try:
            os.close(master_fd)
        except OSError:
            pass

def _terminal_command_error(args, cfg):
    if not args:
        return "No command entered."

    executable = os.path.basename(args[0]).lower()
    blocked = {str(item).lower() for item in cfg.get("blocked_commands", [])}
    if executable in blocked:
        return f"Blocked by terminal_config.yaml: {executable}"

    protected_paths = tuple(str(path) for path in cfg.get("protected_paths", PROTECTED_PATHS))
    for arg in args:
        if arg.startswith("-"):
            continue
        expanded = os.path.abspath(os.path.expanduser(arg))
        for protected in protected_paths:
            if expanded == protected or expanded.startswith(protected.rstrip("/") + "/"):
                return f"Blocked protected path: {arg}"
    return None

def _read_pty(master_fd, max_chars):
    chunks = []
    total = 0
    while True:
        ready, _, _ = select.select([master_fd], [], [], 0)
        if not ready:
            break
        try:
            data = os.read(master_fd, min(4096, max_chars - total))
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
        total += len(data)
        if total >= max_chars:
            chunks.append(b"\r\n[output truncated]\r\n")
            break
    return b"".join(chunks).decode("utf-8", errors="replace")

def _resize_pty(master_fd, cols, rows):
    try:
        import termios
        import struct
        rows = max(10, min(int(rows), 80))
        cols = max(40, min(int(cols), 240))
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


class _FakeMessage:
    def __init__(self, sender, content):
        self.sender = sender
        self.content = content
        self.attachment_filename = None


class _FakeMessages:
    def __init__(self, items=None):
        self._items = items or []
    def count(self):
        return len(self._items)
    def __iter__(self):
        return iter(self._items)


def _is_demo():
    return session.get("is_demo", False) or (current_user.is_authenticated and current_user.id in (-1, -2))


def _group_devices_by_zone(devices):
    from collections import OrderedDict
    zones = OrderedDict()
    for d in devices:
        zone = getattr(d, "location_zone", None)
        if not zone and " — " in (d.name or ""):
            zone = d.name.split(" — ", 1)[0]
        zone = zone or "Other locations"
        zones.setdefault(zone, []).append(d)
    return list(zones.items())


def _sort_demo_fines(fines):
    appeal_rank = {"pending_human": 0, "pending_ai": 1, "none": 2, "approved": 3, "rejected": 4}

    def key(f):
        return (
            0 if not f.resolved else 1,
            appeal_rank.get(f.appeal_status, 9),
            -(f.created_at.timestamp() if f.created_at else 0),
        )

    return sorted(fines, key=key)


def _demo_devices():
    from types import SimpleNamespace
    base = _now()
    fine_counts = {101: 2, 102: 2, 103: 1, 104: 0, 105: 0, 106: 1, 107: 2, 108: 0, 109: 1, 110: 1, 111: 0, 112: 0, 113: 1, 114: 0}

    def make_device(id_, name, spot, plate, status, lat, lng, zone, online=True, wifi=78, temp=52.3, capture=False, notes=None):
        d = SimpleNamespace()
        d.id = id_; d.name = name; d.spot_label = spot; d.assigned_plate = plate
        d.current_status = status; d.is_online = online
        d.mac_address = f"AA:BB:CC:DD:EE:{id_:02X}"
        d.last_seen = base - timedelta(seconds=30 if online else 7200)
        d.last_wifi = wifi; d.last_temp = temp; d.created_at = base - timedelta(days=30)
        d.capture_requested = capture; d.latitude = lat; d.longitude = lng
        d.location_zone = zone; d.notes = notes
        n = fine_counts.get(id_, 0)
        d.fines = SimpleNamespace(count=lambda n=n: n)
        return d

    return [
        make_device(101, "Calea Victoriei — Level 1", "P1-12", "B-123-MAB", "occupied", 44.4383, 26.1034, "Calea Victoriei", wifi=82, temp=51.2, notes="Reserved tenant spot — high traffic"),
        make_device(102, "Calea Victoriei — Level 1", "P1-08", "CJ-45-PQR", "violation", 44.4385, 26.1036, "Calea Victoriei", wifi=61, temp=49.1),
        make_device(103, "Bulevardul Unirii — Surface", "C-03", "B-789-TUV", "empty", 44.4270, 26.1055, "Bulevardul Unirii", wifi=74, temp=48.6),
        make_device(104, "Bulevardul Unirii — Accessible", "H-01", None, "empty", 44.4268, 26.1050, "Bulevardul Unirii", online=False, wifi=None, temp=None, notes="Awaiting plate assignment"),
        make_device(105, "Piata Universitatii — Garage", "P2-04", "B-441-PKR", "correct", 44.4358, 26.1025, "Piata Universitatii", wifi=88, temp=47.9),
        make_device(106, "Strada Franceza — Curbside", "F-12", "AB-12-CDE", "occupied", 44.4312, 26.0988, "Strada Franceza", wifi=70, temp=53.4),
        make_device(107, "Calea Dorobantilor — North", "D-07", "TM-88-XYZ", "violation", 44.4560, 26.0975, "Calea Dorobantilor", wifi=58, temp=55.1, capture=True),
        make_device(108, "Gara de Nord — Drop-off", "GN-01", None, "empty", 44.4465, 26.0745, "Gara de Nord", online=False, wifi=None, temp=None),
        make_device(109, "Herastrau — Lakeside", "H-22", "B-555-LUX", "occupied", 44.4792, 26.0820, "Herastrau", wifi=76, temp=46.8),
        make_device(110, "Pipera — Office Park", "PI-09", "IF-99-KLM", "violation", 44.4935, 26.1188, "Pipera", wifi=64, temp=50.2),
        make_device(111, "Titan — Retail Lot", "T-15", "CL-10-ZZZ", "empty", 44.4168, 26.1520, "Titan", wifi=81, temp=49.5),
        make_device(112, "Drumul Taberei — Block B", "DT-03", "BV-77-ABC", "correct", 44.4120, 26.0340, "Drumul Taberei", wifi=79, temp=48.1),
        make_device(113, "Calea Victoriei — Rooftop", "P3-02", "B-212-GLS", "occupied", 44.4380, 26.1040, "Calea Victoriei", wifi=80, temp=50.0),
        make_device(114, "Old Town — Strada Lipscani", "L-05", None, "empty", 44.4318, 26.1015, "Old Town", wifi=72, temp=47.2, notes="Pi arriving Thursday"),
    ]


def _demo_fines():
    from types import SimpleNamespace
    base = _now()
    devices = {d.id: d for d in _demo_devices()}
    def make_fine(id_, dev_id, detected, expected, mins, resolved=False, appeal="none", confidence=91.0,
                  photo_requested=False, photo_sent=False, hours_ago=None):
        f = SimpleNamespace()
        f.id = id_; f.device_id = dev_id; f.device = devices.get(dev_id)
        f.detected_plate = detected; f.expected_plate = expected
        f.duration_minutes = mins; f.resolved = resolved; f.appeal_status = appeal
        f.confidence_score = confidence
        f.image_filename = "demo_evidence.jpg" if not resolved else None
        ago = hours_ago if hours_ago is not None else id_ * 3
        f.first_seen = base - timedelta(hours=ago, minutes=mins)
        f.last_seen = f.first_seen + timedelta(minutes=mins)
        f.created_at = base - timedelta(hours=ago)
        f.photo_requested = photo_requested
        f.photo_sent_at = (base - timedelta(hours=ago - 1)) if photo_sent else None
        f.appeal_reason = None; f.last_notified = None
        f.messages = _FakeMessages()
        return f

    fines = [
        make_fine(1, 101, "B-900-ZAB", "B-123-MAB", 47, confidence=94.2, photo_requested=True, hours_ago=1),
        make_fine(2, 102, "CJ-45-PQR", "CJ-45-PQR", 128, resolved=True, hours_ago=48),
        make_fine(3, 103, "IF-22-RST", "B-789-TUV", 22, confidence=87.4, hours_ago=2),
        make_fine(4, 101, "B-600-WXY", "B-123-MAB", 185, appeal="pending_human", confidence=92.8, hours_ago=6),
        make_fine(5, 107, "B-111-WRG", "TM-88-XYZ", 64, confidence=93.2, hours_ago=3),
        make_fine(6, 110, "B-200-FKE", "IF-99-KLM", 38, confidence=89.6, hours_ago=4),
        make_fine(7, 106, "GL-55-NNN", "AB-12-CDE", 95, confidence=91.8, hours_ago=8),
        make_fine(8, 109, "B-999-XXX", "B-555-LUX", 12, confidence=84.1, hours_ago=0.5),
        make_fine(9, 107, "PH-44-QQQ", "TM-88-XYZ", 210, resolved=True, appeal="approved", confidence=88.0, hours_ago=72),
        make_fine(10, 102, "CJ-99-ZZZ", "CJ-45-PQR", 55, appeal="pending_ai", confidence=76.5, hours_ago=5),
        make_fine(11, 113, "B-808-DLV", "B-212-GLS", 31, confidence=90.1, hours_ago=2.5),
        make_fine(12, 106, "AB-12-CDE", "AB-12-CDE", 18, resolved=True, confidence=98.0, hours_ago=12),
    ]

    fines[3].messages = _FakeMessages([
        _FakeMessage("System",
            "Violation recorded: B-600-WXY in spot P1-12 (assigned B-123-MAB) for 185 minutes."),
        _FakeMessage("Maria Constantin",
            "My brother borrowed the spot while my car was at the mechanic. I can share the garage receipt."),
        _FakeMessage("AI Assessor",
            "No guest-access record for P1-12 today. Escalating to human review."),
        _FakeMessage("Maria Constantin",
            "Uploaded invoice + written permission from building admin. Please waive this alert."),
    ])
    fines[9].messages = _FakeMessages([
        _FakeMessage("Andrei Popescu", "Visitor stayed longer than expected — loading event supplies."),
        _FakeMessage("AI Assessor",
            "OCR confidence 76.5%. Pattern matches repeat plate CJ-99-ZZZ. Recommend admin review."),
    ])
    return _sort_demo_fines(fines)


def _demo_activity_feed():
    from types import SimpleNamespace
    base = _now()
    return [
        SimpleNamespace(when=base - timedelta(minutes=4), level="danger", title="New violation", detail="P1-12 — detected B-900-ZAB (expected B-123-MAB)"),
        SimpleNamespace(when=base - timedelta(minutes=18), level="warning", title="Appeal submitted", detail="Maria Constantin — spot P1-12 human review"),
        SimpleNamespace(when=base - timedelta(minutes=42), level="info", title="Capture completed", detail="Calea Dorobantilor D-07 — admin requested snapshot"),
        SimpleNamespace(when=base - timedelta(hours=2), level="success", title="Violation resolved", detail="TM-88-XYZ — appeal approved, evidence verified"),
        SimpleNamespace(when=base - timedelta(hours=5), level="muted", title="Device offline", detail="Gara de Nord GN-01 — no heartbeat for 2h"),
        SimpleNamespace(when=base - timedelta(hours=8), level="info", title="Plate assigned", detail="Piata Universitatii P2-04 → B-441-PKR"),
    ]


def _demo_users():
    from types import SimpleNamespace
    base = _now()
    def mu(id_, name, email, plate, role, status, days_ago=0):
        u = SimpleNamespace()
        u.id = id_; u.name = name; u.email = email; u.license_plate = plate
        u.role = role; u.verification_status = status; u.is_admin = (role == "admin")
        u.created_at = base - timedelta(days=days_ago)
        u.verification_document = None
        normalized = re.sub(r"[^A-Z0-9]", "", (plate or "").upper())
        u.plate_values = (lambda p=normalized: [p] if p else [])
        return u
    users = [
        mu(1, "Maria Constantin",  "maria.constantin@gmail.com",  "B-123-MAB", "driver", "approved", 45),
        mu(2, "Andrei Popescu",    "andrei.popescu@yahoo.com",    "CJ-45-PQR", "driver", "approved", 30),
        mu(3, "Elena Ionescu",     "e.ionescu@gmail.com",         "B-789-TUV", "driver", "pending",   3),
        mu(4, "Radu Dumitrescu",   "radu.d@outlook.com",          "IF-22-RST", "driver", "pending",   1),
        mu(5, "Cristina Munteanu", "cristina.munteanu@gmail.com", "B-441-PKR", "driver", "rejected", 20),
        mu(7, "Vlad Petrescu",     "vlad.petrescu@gmail.com",     "TM-88-XYZ", "driver", "approved", 14),
        mu(8, "Ioana Georgescu",   "ioana.g@company.ro",          "IF-99-KLM", "driver", "approved", 7),
        mu(6, "Admin",             "admin@parkscan.ro",           "",           "admin",  "approved", 90),
    ]
    users[2].verification_document = "demo_id_elena.jpg"
    users[3].verification_document = "demo_registration_radu.pdf"
    return users


def _get_device_by_mac(mac):
    return Device.query.filter_by(mac_address=mac).first()


def normalize_plate(plate):
    return re.sub(r"[^A-Z0-9]", "", (plate or "").upper())


def is_valid_plate(plate):
    normalized = normalize_plate(plate)
    return 5 <= len(normalized) <= 10 and any(char.isalpha() for char in normalized) and any(char.isdigit() for char in normalized)


def user_plate_values(user):
    if hasattr(user, "plate_list"):
        return list(user.plate_list)
    if hasattr(user, "plates") and hasattr(user.plates, "all"):
        return user.plate_values()
    legacy = normalize_plate(getattr(user, "license_plate", ""))
    return [legacy] if legacy else []


def user_owns_plate(user, plate):
    normalized = normalize_plate(plate)
    return normalized in user_plate_values(user)


def find_user_by_plate(plate):
    normalized = normalize_plate(plate)
    if not normalized:
        return None
    row = UserPlate.query.filter_by(plate=normalized, verification_status="approved").first()
    if row:
        return row.user
    return User.query.filter_by(license_plate=normalized).first()


def save_plate_proof_upload(file_storage) -> tuple[str, str]:
    """Save PDF/DOCX proof; returns (stored_filename relative to uploads, mime_type)."""
    if not file_storage or not file_storage.filename:
        raise ValueError("No document uploaded")

    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    if ext not in config.PLATE_PROOF_EXTENSIONS:
        raise ValueError("Upload a PDF or DOCX from city hall, police, or vehicle registration.")

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > config.MAX_PLATE_PROOF_BYTES:
        raise ValueError("Document must be 8 MB or smaller.")

    proof_dir = os.path.join(app.config["UPLOAD_FOLDER"], "plate_proofs")
    os.makedirs(proof_dir, exist_ok=True)
    stored = f"plate_{uuid.uuid4().hex[:12]}_{secure_filename(file_storage.filename)}"
    file_storage.save(os.path.join(proof_dir, stored))
    mime = config.PLATE_PROOF_MIME_TYPES.get(ext, "application/octet-stream")
    return f"plate_proofs/{stored}", mime


def sync_user_primary_plate(user):
    plates = user.plate_values()
    user.license_plate = plates[0] if plates else ""


def migrate_legacy_user_plates():
    for user in User.query.filter(User.role == "driver").all():
        legacy_plate = normalize_plate(user.license_plate)
        if legacy_plate and not UserPlate.query.filter_by(plate=legacy_plate).first():
            db.session.add(
                UserPlate(
                    user_id=user.id,
                    plate=legacy_plate,
                    verification_status="approved",
                    verified_at=_now(),
                )
            )
        if user.verification_status != "approved":
            user.verification_status = "approved"
    for row in UserPlate.query.all():
        if not row.verification_status:
            row.verification_status = "approved"
        if row.verification_status == "approved" and not row.verified_at:
            row.verified_at = _now()
    db.session.commit()


with app.app_context():
    migrate_legacy_user_plates()


def allowed_proof_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_PROOF_EXTENSIONS


def save_verification_document(file_storage, plate):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_proof_file(file_storage.filename):
        return None

    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    safe_plate = secure_filename(normalize_plate(plate))
    filename = f"plate_proof_{safe_plate}_{uuid.uuid4().hex[:10]}.{ext}"
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return filename

# ---------------------------------------------------------------------------
# API — Device management
# ---------------------------------------------------------------------------

@app.route("/api/devices/register", methods=["POST"])
def api_register_device():
    """Register a new device or return existing one."""
    data = request.get_json(force=True)
    mac = data.get("mac_address", "").strip().upper()
    if not mac:
        return jsonify({"error": "mac_address is required"}), 400

    device = _get_device_by_mac(mac)
    if device is None:
        device = Device(
            mac_address=mac,
            name=data.get("name", f"Pi-{mac[-5:].replace(':', '')}"),
            last_seen=_now(),
        )
        db.session.add(device)
        db.session.commit()
    else:
        device.last_seen = _now()
        db.session.commit()

    return jsonify(device.to_dict()), 200


@app.route("/api/devices/<mac>/heartbeat", methods=["POST"])
def api_heartbeat(mac):
    """Update device last_seen timestamp."""
    device = _get_device_by_mac(mac.upper())
    if device is None:
        return jsonify({"error": "Device not found"}), 404
        
    data = request.get_json(force=True, silent=True) or {}
    device.last_seen = _now()
    
    wifi = data.get("wifi_strength")
    temp = data.get("temperature")
    spot_status = data.get("spot_status", "empty")
    if wifi is not None:
        device.last_wifi = wifi
    if temp is not None:
        device.last_temp = temp
    device.current_status = spot_status
        
    action = None
    if device.capture_requested:
        action = "capture_now"
        device.capture_requested = False
        
    db.session.commit()
    broadcast_sse("device_update", device.to_dict())
    return jsonify({"status": "ok", "is_online": True, "action": action}), 200


@app.route("/api/devices/<mac>/config", methods=["GET"])
def api_get_device_config(mac):
    """Return the assigned plate and schedule for a device."""
    device = _get_device_by_mac(mac.upper())
    if device is None:
        return jsonify({"error": "Device not found"}), 404
    return jsonify({
        "assigned_plate": device.assigned_plate,
        "spot_label": device.spot_label,
        "name": device.name,
    }), 200


@app.route("/api/devices", methods=["GET"])
def api_list_devices():
    """List all registered devices."""
    devices = Device.query.order_by(Device.created_at.desc()).all()
    return jsonify([d.to_dict() for d in devices]), 200

# ---------------------------------------------------------------------------
# API — Web Push
# ---------------------------------------------------------------------------

@app.route("/api/push/public-key", methods=["GET"])
def push_public_key():
    return jsonify({"publicKey": VAPID_PUBLIC_KEY})

@app.route("/api/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    subscription_info = request.json
    if not subscription_info:
        return jsonify({"error": "No subscription data provided"}), 400
        
    sub_json = json.dumps(subscription_info)
    
    # Check if this exact subscription already exists for this user
    existing = PushSubscription.query.filter_by(
        user_id=current_user.id,
        subscription_info=sub_json
    ).first()
    
    if not existing:
        new_sub = PushSubscription(user_id=current_user.id, subscription_info=sub_json)
        db.session.add(new_sub)
        db.session.commit()
        
    return jsonify({"status": "ok"}), 201

def send_web_push(user, title, body):
    if not VAPID_PRIVATE_KEY:
        return
        
    subs = PushSubscription.query.filter_by(user_id=user.id).all()
    message = json.dumps({"title": title, "body": body})
    
    for sub in subs:
        try:
            sub_info = json.loads(sub.subscription_info)
            webpush(
                subscription_info=sub_info,
                data=message,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
        except WebPushException as ex:
            # Often means subscription expired or revoked
            if ex.response and ex.response.status_code in [404, 410]:
                db.session.delete(sub)
        except Exception as e:
            print(f"Error sending push: {e}")
            
    try:
        db.session.commit()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# API — Fines
# ---------------------------------------------------------------------------

@app.route("/api/fines", methods=["POST"])
def api_report_fine():
    """Client reports a plate mismatch."""
    mac = request.form.get("mac_address", "").strip().upper()
    detected_plate = normalize_plate(request.form.get("detected_plate", ""))
    expected_plate = normalize_plate(request.form.get("expected_plate", ""))
    first_seen_str = request.form.get("first_seen", "")
    duration_minutes = int(request.form.get("duration_minutes", 0))

    if not mac or not detected_plate:
        return jsonify({"error": "mac_address and detected_plate are required"}), 400

    device = _get_device_by_mac(mac)
    if device is None:
        return jsonify({"error": "Device not found"}), 404

    # Handle uploaded evidence image
    image_filename = None
    if "image" in request.files:
        f = request.files["image"]
        if f.filename:
            safe_name = secure_filename(f"{mac}_{_now().strftime('%Y%m%d_%H%M%S')}_{f.filename}")
            f.save(os.path.join(app.config["UPLOAD_FOLDER"], safe_name))
            image_filename = safe_name

    confidence_score = float(request.form.get("confidence_score", 0.0))

    # Parse first_seen
    try:
        first_seen = datetime.fromisoformat(first_seen_str)
    except (ValueError, TypeError):
        first_seen = _now()

    fine = Fine(
        device_id=device.id,
        detected_plate=detected_plate,
        expected_plate=expected_plate or (device.assigned_plate or "N/A"),
        image_filename=image_filename,
        first_seen=first_seen,
        last_seen=_now(),
        duration_minutes=duration_minutes,
        confidence_score=confidence_score,
    )
    
    if confidence_score < 60:
        fine.appeal_status = "pending_human"
    elif confidence_score < 80:
        fine.appeal_status = "pending_ai"
        # Process AI logic in background
        threading.Thread(target=_run_ai_background, args=(app._get_current_object(), fine.id)).start()
    else:
        fine.appeal_status = "none"

    db.session.add(fine)
    db.session.commit()
    broadcast_sse("new_fine", fine.to_dict())

    # Notify user if expected plate matches a registered user using throttling
    if fine.expected_plate:
        user = find_user_by_plate(fine.expected_plate)
        if user:
            recent_alert = Fine.query.filter(
                Fine.expected_plate == fine.expected_plate,
                Fine.detected_plate == fine.detected_plate,
                Fine.last_notified != None,
                Fine.last_notified >= _now() - timedelta(hours=4)
            ).first()
            if not recent_alert:
                send_web_push(user, "New Parking Alert!", f"An unauthorized vehicle ({detected_plate}) has been parked in your spot for {duration_minutes} mins.")
                fine.last_notified = _now()
                db.session.commit()

    return jsonify(fine.to_dict()), 201


@app.route("/api/fines/<int:fine_id>", methods=["PATCH"])
def api_update_fine(fine_id):
    """Mark a fine as resolved."""
    fine = Fine.query.get_or_404(fine_id)
    data = request.get_json(force=True)
    if "resolved" in data:
        fine.resolved = bool(data["resolved"])
    db.session.commit()
    return jsonify(fine.to_dict()), 200


@app.route("/api/fines", methods=["GET"])
def api_list_fines():
    """List all fines, newest first."""
    fines = Fine.query.order_by(Fine.created_at.desc()).all()
    return jsonify([f.to_dict() for f in fines]), 200

# ---------------------------------------------------------------------------
# Dashboard — Pages (Admin)
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('dashboard'))
        return redirect(url_for('portal'))
    return redirect(url_for('login'))

@app.route("/admin")
@require_admin
def dashboard():
    if _is_demo():
        devices = _demo_devices()
        all_fines = _demo_fines()
        pending_users = [u for u in _demo_users() if u.verification_status == "pending"]
        chart_labels = [(_now() - timedelta(days=i)).strftime("%a") for i in range(6, -1, -1)]
        chart_data = [4, 7, 5, 11, 8, 6, 9]
        return render_template(
            "dashboard.html",
            devices=devices,
            fines=all_fines,
            pending_users=pending_users,
            pending_plates=[],
            chart_labels=chart_labels,
            chart_data=chart_data,
            device_zones=_group_devices_by_zone(devices),
            activity_feed=_demo_activity_feed(),
            is_demo=True,
        )

    devices = Device.query.order_by(Device.created_at.desc()).all()
    recent_fines = Fine.query.order_by(Fine.created_at.desc()).limit(20).all()
    pending_users = []

    sevendays_ago = _now() - timedelta(days=6)
    last_7_fines = Fine.query.filter(Fine.created_at >= sevendays_ago).all()

    day_counts = {}
    for i in range(7):
        day_str = (_now() - timedelta(days=i)).strftime("%a")
        day_counts[day_str] = 0

    for f in last_7_fines:
        if f.created_at:
            d_str = f.created_at.strftime("%a")
            if d_str in day_counts:
                day_counts[d_str] += 1

    chart_labels = list(reversed(list(day_counts.keys())))
    chart_data = [day_counts[l] for l in chart_labels]

    pending_plates = (
        UserPlate.query.filter_by(verification_status="pending")
        .order_by(UserPlate.created_at.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "dashboard.html",
        devices=devices,
        fines=recent_fines,
        pending_users=pending_users,
        pending_plates=pending_plates,
        chart_labels=chart_labels,
        chart_data=chart_data,
        device_zones=_group_devices_by_zone(devices),
        activity_feed=[],
    )


@app.route("/device/<int:device_id>")
@require_admin
def device_detail(device_id):
    if _is_demo():
        device = next((d for d in _demo_devices() if d.id == device_id), None)
        if not device:
            flash("Device not found in demo data.", "warning")
            return redirect(url_for("dashboard"))
        fines = [f for f in _demo_fines() if f.device_id == device_id]
        return render_template("device_detail.html", device=device, fines=fines, is_demo=True)
    device = Device.query.get_or_404(device_id)
    fines = device.fines.order_by(Fine.created_at.desc()).all()
    return render_template("device_detail.html", device=device, fines=fines)


@app.route("/device/<int:device_id>/update", methods=["POST"])
@require_admin
def device_update(device_id):
    if _is_demo():
        flash("Demo mode — no changes are saved.", "info")
        return redirect(url_for("device_detail", device_id=device_id))
    device = Device.query.get_or_404(device_id)
    device.name = request.form.get("name", device.name).strip()
    device.spot_label = request.form.get("spot_label", device.spot_label).strip()
    plate = normalize_plate(request.form.get("assigned_plate", ""))
    device.assigned_plate = plate if plate else None
    notes = request.form.get("notes", "").strip()
    device.notes = notes if notes else None
    db.session.commit()
    flash(f"Device {device.name} updated.", "success")
    return redirect(url_for("device_detail", device_id=device.id))


@app.route("/device/<int:device_id>/capture_now", methods=["POST"])
@require_admin
def device_capture_now(device_id):
    if _is_demo():
        flash("Demo mode — capture request not sent.", "info")
        return redirect(url_for("device_detail", device_id=device_id))
    device = Device.query.get_or_404(device_id)
    device.capture_requested = True
    db.session.commit()
    flash(f"Immediate capture requested for {device.name}. It will execute on the next Pi heartbeat.", "info")
    return redirect(url_for("device_detail", device_id=device.id))


@app.route("/device/<int:device_id>/delete", methods=["POST"])
@require_admin
def device_delete(device_id):
    if _is_demo():
        flash("Demo mode — no changes are saved.", "info")
        return redirect(url_for("dashboard"))
    device = Device.query.get_or_404(device_id)
    Fine.query.filter_by(device_id=device.id).delete()
    db.session.delete(device)
    db.session.commit()
    flash("Device deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/device/<int:device_id>/set_location", methods=["POST"])
@require_admin
def device_set_location(device_id):
    if _is_demo():
        flash("Demo mode — no changes are saved.", "info")
        return redirect(url_for("device_detail", device_id=device_id))
    device = Device.query.get_or_404(device_id)
    try:
        device.latitude = float(request.form.get("latitude", ""))
        device.longitude = float(request.form.get("longitude", ""))
    except (ValueError, TypeError):
        flash("Invalid coordinates.", "danger")
        return redirect(url_for("device_detail", device_id=device.id))
    db.session.commit()
    flash("Location saved.", "success")
    return redirect(url_for("device_detail", device_id=device.id))


@app.route("/device/<int:device_id>/replace_pi", methods=["POST"])
@require_admin
def device_replace_pi(device_id):
    if _is_demo():
        flash("Demo mode — no changes are saved.", "info")
        return redirect(url_for("device_detail", device_id=device_id))
    old_device = Device.query.get_or_404(device_id)
    new_mac = request.form.get("new_mac", "").strip().upper()
    transfer_history = request.form.get("transfer_history") == "on"

    if not new_mac:
        flash("New MAC address is required.", "danger")
        return redirect(url_for("device_detail", device_id=device_id))

    existing = Device.query.filter_by(mac_address=new_mac).first()
    if existing and existing.id != old_device.id:
        new_device = existing
    else:
        new_device = Device(mac_address=new_mac, last_seen=None)
        db.session.add(new_device)
        db.session.flush()

    new_device.name = old_device.name
    new_device.spot_label = old_device.spot_label
    new_device.assigned_plate = old_device.assigned_plate
    new_device.latitude = old_device.latitude
    new_device.longitude = old_device.longitude
    new_device.notes = old_device.notes

    if transfer_history:
        Fine.query.filter_by(device_id=old_device.id).update({"device_id": new_device.id})

    db.session.delete(old_device)
    db.session.commit()
    flash(f"Pi replaced. Configuration transferred to {new_mac}.", "success")
    return redirect(url_for("device_detail", device_id=new_device.id))


@app.route("/analytics")
@require_admin
def analytics():
    if _is_demo():
        devices = _demo_devices()
        fines = _demo_fines()
    else:
        devices = Device.query.all()
        fines = Fine.query.order_by(Fine.created_at.desc()).all()

    total_fines = len(fines)
    resolved_fines = sum(1 for f in fines if f.resolved)
    active_fines = total_fines - resolved_fines

    plate_counts = {}
    for f in fines:
        plate_counts[f.detected_plate] = plate_counts.get(f.detected_plate, 0) + 1
    top_plates = sorted(plate_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    hour_counts = {str(h).zfill(2) + ":00": 0 for h in range(24)}
    for f in fines:
        if f.created_at:
            h = f.created_at.strftime("%H") + ":00"
            hour_counts[h] = hour_counts.get(h, 0) + 1

    device_counts = {}
    for f in fines:
        dname = f.device.name if f.device else "Unknown"
        device_counts[dname] = device_counts.get(dname, 0) + 1
    top_devices = sorted(device_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    avg_duration = (sum(f.duration_minutes for f in fines) / total_fines) if total_fines else 0

    return render_template("analytics.html",
        devices=devices, fines=fines,
        total_fines=total_fines, resolved_fines=resolved_fines, active_fines=active_fines,
        top_plates=top_plates, hour_counts=hour_counts, top_devices=top_devices,
        avg_duration=round(avg_duration, 1), is_demo=_is_demo())


@app.route("/admin/users")
@require_admin
def users_page():
    if _is_demo():
        return render_template("users.html", users=_demo_users(), is_demo=True)

    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("users.html", users=users)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@require_admin
def delete_user(user_id):
    if _is_demo():
        flash("Demo mode — no changes are saved.", "info")
        return redirect(url_for("users_page"))
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        abort(400)
    db.session.delete(user)
    db.session.commit()
    flash("User deleted.", "success")
    return redirect(url_for("users_page"))


@app.route("/fines/export.csv")
@require_admin
def export_fines_csv():
    import csv
    import io
    if _is_demo():
        fines = _demo_fines()
    else:
        fines = Fine.query.order_by(Fine.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Device", "Spot", "Detected Plate", "Expected Plate",
                     "First Seen", "Duration (min)", "Confidence", "Resolved", "Appeal Status"])
    for f in fines:
        writer.writerow([
            f.id,
            f.device.name if f.device else "",
            f.device.spot_label if f.device else "",
            f.detected_plate, f.expected_plate,
            f.first_seen.strftime("%Y-%m-%d %H:%M") if f.first_seen else "",
            f.duration_minutes,
            f.confidence_score,
            "Yes" if f.resolved else "No",
            f.appeal_status,
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=fines_export.csv"},
    )


@app.route("/fines")
@require_admin
def fines_page():
    if _is_demo():
        return render_template("dashboard.html",
                               devices=_demo_devices(), fines=_demo_fines(),
                               pending_users=[], show_all_fines=True, is_demo=True)
    fines = Fine.query.order_by(Fine.created_at.desc()).all()
    return render_template("dashboard.html",
                           devices=Device.query.all(),
                           fines=fines,
                           show_all_fines=True)


@app.route("/fine/<int:fine_id>/resolve", methods=["POST"])
@require_admin
def resolve_fine(fine_id):
    if _is_demo():
        flash("Demo mode — no changes are saved.", "info")
        return redirect(request.referrer or url_for("dashboard"))
    fine = Fine.query.get_or_404(fine_id)
    fine.resolved = not fine.resolved
    db.session.commit()
    flash(f"Fine #{fine.id} {'resolved' if fine.resolved else 'reopened'}.", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/uploads/<path:filename>")
@login_required
def serve_upload(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/admin/users/<int:user_id>/verify/<action>", methods=["POST"])
@require_admin
def verify_user(user_id, action):
    if _is_demo():
        flash("Demo mode — no changes are saved.", "info")
        return redirect(request.referrer or url_for("dashboard"))
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        abort(400)

    if action == "approve":
        user.verification_status = "approved"
        user.verification_notes = "Approved by admin."
        flash(f"{user.name}'s plate was approved.", "success")
    elif action == "reject":
        user.verification_status = "rejected"
        user.verification_notes = request.form.get("verification_notes", "").strip() or "Proof did not match the requested plate."
        flash(f"{user.name}'s plate proof was rejected.", "warning")
    else:
        abort(404)

    db.session.commit()
    return redirect(url_for("dashboard"))

# ---------------------------------------------------------------------------
# Auth — Routes
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    return redirect(url_for("login", mode="admin"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard" if current_user.is_admin else "portal"))

    if request.method == "POST":
        form_action = request.form.get("form_action", "login")
        account_type = request.form.get("account_type", "driver")
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "")

        if form_action == "signup":
            name = request.form.get("name", "").strip() or ("Administrator" if account_type == "admin" else "Driver")
            role = "admin" if account_type == "admin" else "driver"

            if not email or not password:
                flash("Email and password are required.", "danger")
                return redirect(url_for("login", mode="signup", account_type=role))

            if len(password) < 8:
                flash("Use at least 8 characters for the password.", "danger")
                return redirect(url_for("login", mode="signup", account_type=role))

            if User.query.filter_by(email=email).first():
                flash("That email is already registered.", "danger")
                return redirect(url_for("login", mode="signup", account_type=role))

            if role == "admin":
                invite_code = request.form.get("admin_invite_code", "")
                if invite_code != config.ADMIN_SIGNUP_CODE:
                    flash("Admin invite code is not valid.", "danger")
                    return redirect(url_for("login", mode="signup", account_type="admin"))
                verification_status = "approved"
                plate = ""
            else:
                verification_status = "approved"
                plate = ""

            hashed = bcrypt.generate_password_hash(password).decode("utf-8")
            user = User(
                email=email,
                password_hash=hashed,
                license_plate=plate,
                name=name,
                role=role,
                verification_status=verification_status,
            )
            db.session.add(user)
            db.session.commit()

            if user.is_admin:
                login_user(user)
                flash("Admin account created.", "success")
                return redirect(url_for("dashboard"))

            login_user(user)
            flash(
                "Account created. Add each license plate in settings with a PDF or DOCX "
                "registration document from city hall or police — we verify it automatically.",
                "success",
            )
            return redirect(url_for("account_settings"))

        user = User.query.filter_by(email=email).first()

        is_demo = email == "demo" and password == "demo123!"
        if is_demo:
            if account_type == "admin":
                demo_admin = User(email="demo", password_hash="", license_plate="", role="admin", verification_status="approved")
                demo_admin.id = -1
                demo_admin.name = "Demo Admin"
                session["is_demo"] = True
                login_user(demo_admin)
                return redirect(url_for("dashboard"))
            else:
                demo_user = User(email="demo", password_hash="", license_plate="B-123-MAB", role="driver", verification_status="approved")
                demo_user.id = -2
                demo_user.name = "Demo User"
                demo_user.plate_list = ["B123MAB"]
                session["is_demo"] = True
                login_user(demo_user)
                return redirect(url_for("portal"))

        is_test_admin = email == "admin" and password == "admin123!"
        is_configured_admin = email == config.ADMIN_USERNAME and bcrypt.check_password_hash(config.ADMIN_PASSWORD_HASH, password)

        if account_type == "admin" and (is_test_admin or is_configured_admin):
            admin_user = User(id=0, email="admin", password_hash="", license_plate="", role="admin", verification_status="approved")
            admin_user.name = "Admin"
            login_user(admin_user)
            return redirect(url_for("dashboard"))

        if user and bcrypt.check_password_hash(user.password_hash, password):
            if account_type == "admin" and not user.is_admin:
                flash("This account is not an admin account.", "danger")
            elif account_type == "driver" and user.is_admin:
                flash("Use the admin sign-in option for this account.", "danger")
            else:
                login_user(user)
                return redirect(url_for("dashboard" if user.is_admin else "portal"))
        else:
            flash("Invalid email or password.", "danger")

    return render_template("user_login.html")

@app.route("/logout")
@login_required
def logout():
    session.pop("is_demo", None)
    logout_user()
    return redirect(url_for("index"))

# ---------------------------------------------------------------------------
# Local Terminal — Lightweight Admin Tool
# ---------------------------------------------------------------------------

@app.route("/terminal/login", methods=["GET", "POST"])
def terminal_login():
    cfg = load_terminal_config()
    if not cfg.get("enabled", True):
        abort(404)
    if not _terminal_remote_allowed(cfg):
        abort(403)

    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        expected_user = str(cfg.get("username", "admin"))
        expected_pass = str(cfg.get("password", "admin123!"))
        if hmac.compare_digest(username, expected_user) and hmac.compare_digest(password, expected_pass):
            session["terminal_admin"] = True
            session.permanent = False
            _terminal_csrf_token()
            return redirect(url_for("terminal_page"))
        error = "Invalid terminal username or password."

    return render_template(
        "terminal_login.html",
        error=error,
        loopback_only=cfg.get("loopback_only", True),
    )

@app.route("/terminal/logout", methods=["POST"])
@require_terminal_login
def terminal_logout():
    if not _valid_terminal_csrf():
        abort(400)
    _close_terminal_session(session.get("terminal_sid"))
    session.pop("terminal_admin", None)
    session.pop("terminal_csrf", None)
    session.pop("terminal_sid", None)
    return redirect(url_for("terminal_login"))

@app.route("/terminal", methods=["GET"])
@require_terminal_login
def terminal_page():
    cfg = load_terminal_config()
    return render_template(
        "terminal.html",
        csrf_token=_terminal_csrf_token(),
        cwd=_terminal_cwd(cfg),
        blocked_commands=cfg.get("blocked_commands", []),
        timeout=cfg.get("command_timeout_seconds", 8),
    )

@app.route("/terminal/run", methods=["POST"])
@require_terminal_login
def terminal_run():
    if not _valid_terminal_csrf():
        abort(400)
    cfg = load_terminal_config()
    command = request.form.get("command", "").strip()
    if "\x00" in command or "\n" in command or "\r" in command:
        return jsonify({"error": "Rejected: command must be a single line."}), 400
    try:
        args = shlex.split(command)
    except ValueError as exc:
        return jsonify({"error": f"Parse error: {exc}"}), 400

    error = _terminal_command_error(args, cfg)
    if error:
        return jsonify({"error": error}), 400

    sid = _terminal_sid()
    _close_terminal_session(sid)

    master_fd, slave_fd = pty.openpty()
    _resize_pty(master_fd, request.form.get("cols", 100), request.form.get("rows", 30))
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "HOME": os.path.expanduser("~"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "TERM": "xterm-256color",
    }
    try:
        proc = subprocess.Popen(
            args,
            cwd=_terminal_cwd(cfg),
            env=env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            close_fds=True,
        )
    except FileNotFoundError:
        os.close(master_fd)
        os.close(slave_fd)
        return jsonify({"error": f"Command not found: {args[0]}"}), 404
    finally:
        try:
            os.close(slave_fd)
        except OSError:
            pass

    with TERMINAL_LOCK:
        TERMINAL_SESSIONS[sid] = {
            "process": proc,
            "master_fd": master_fd,
            "started_at": datetime.now(timezone.utc),
            "max_output_chars": int(cfg.get("max_output_chars", 20000)),
        }
    return jsonify({"status": "started"})

@app.route("/terminal/input", methods=["POST"])
@require_terminal_login
def terminal_input():
    if not _valid_terminal_csrf():
        abort(400)
    sid = _terminal_sid()
    with TERMINAL_LOCK:
        term = TERMINAL_SESSIONS.get(sid)
    if not term:
        return jsonify({"error": "No active terminal session."}), 404
    data = request.form.get("data", "")
    if len(data) > 4096:
        return jsonify({"error": "Input too large."}), 400
    try:
        os.write(term["master_fd"], data.encode("utf-8", errors="ignore"))
    except OSError:
        return jsonify({"error": "Terminal session is closed."}), 410
    return jsonify({"status": "ok"})

@app.route("/terminal/poll", methods=["GET"])
@require_terminal_login
def terminal_poll():
    sid = _terminal_sid()
    with TERMINAL_LOCK:
        term = TERMINAL_SESSIONS.get(sid)
    if not term:
        return jsonify({"output": "", "running": False})
    proc = term["process"]
    output = _read_pty(term["master_fd"], term.get("max_output_chars", 20000))
    running = proc.poll() is None
    if not running:
        output += f"\r\n[process exited with code {proc.returncode}]\r\n"
        _close_terminal_session(sid)
    return jsonify({"output": output, "running": running})

@app.route("/terminal/resize", methods=["POST"])
@require_terminal_login
def terminal_resize():
    if not _valid_terminal_csrf():
        abort(400)
    sid = _terminal_sid()
    with TERMINAL_LOCK:
        term = TERMINAL_SESSIONS.get(sid)
    if term:
        _resize_pty(term["master_fd"], request.form.get("cols", 100), request.form.get("rows", 30))
    return jsonify({"status": "ok"})

@app.route("/api/users/register", methods=["POST"])
def api_register_user():
    """Register a new driver user from JSON clients."""
    data = request.get_json(force=True)
    
    email = data.get("email", "").lower().strip()
    password = data.get("password", "")
    name = data.get("name", "Driver").strip()
    
    if not all([email, password]):
         return jsonify({"error": "email and password are required"}), 400
         
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 400
        
    hashed = bcrypt.generate_password_hash(password).decode('utf-8')
    user = User(
        email=email,
        password_hash=hashed,
        license_plate="",
        name=name,
        role="driver",
        verification_status="approved",
    )
    
    db.session.add(user)
    db.session.commit()
    
    return jsonify({"status": "ok", "message": "User registered"}), 201

# ---------------------------------------------------------------------------
# Appeals & AI
# ---------------------------------------------------------------------------

import base64
import requests
import cv2
import numpy as np

def enhance_image_for_night(filepath):
    try:
        img = cv2.imread(filepath)
        if img is None:
            return
            
        yuv = cv2.cvtColor(img, cv2.COLOR_BGR2YUV)
        mean_luma = np.mean(yuv[:, :, 0])
        
        if mean_luma < 60:
            print("[OPENCV] Low light detected. Enhancing...")
            yuv[:, :, 0] = cv2.equalizeHist(yuv[:, :, 0])
            enhanced = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)
            cv2.imwrite(filepath, enhanced)
    except Exception as e:
        print(f"[OPENCV] Enhancement failed: {e}")

def analyze_appeal_with_ollama(fine):
    """Hits local Ollama instance with qwen3-vl:2b to check if fine is valid."""
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], fine.image_filename)
    if not os.path.exists(filepath):
        return False, "Evidence missing"
        
    try:
        enhance_image_for_night(filepath)
        
        with open(filepath, "rb") as img_file:
            img_b64 = base64.b64encode(img_file.read()).decode("utf-8")
            
        prompt = f"Analyze the license plate in this image. Is the license plate {fine.expected_plate}? Reply strictly with 'yes' or 'no'."
        
        payload = {
            "model": "qwen3-vl:2b",
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
            "options": {
                "num_gpu": 999 
            }
        }
        
        response = requests.post("http://localhost:11434/api/generate", json=payload, timeout=600)
        response.raise_for_status()
        
        result_text = response.json().get("response", "").strip().lower()
        
        # 'yes' means it IS the owners car -> fine is wrong. Wait, the user wants strictly 'right' or 'wrong'.
        # Let's map 'yes' -> 'wrong' fine, 'no' -> 'right' fine.
        is_fine_wrong = "yes" in result_text
        return True, is_fine_wrong
        
    except Exception as e:
        print(f"[OLLAMA] Error: {e}")
        return False, str(e)

def _run_ai_background(app_obj, fine_id):
    with app_obj.app_context():
        fine = Fine.query.get(fine_id)
        if fine:
            success, is_fine_wrong = analyze_appeal_with_ollama(fine)
            if success:
                if is_fine_wrong:
                    fine.appeal_status = "approved"
                    fine.resolved = True
                    ai_details = f"I detected plate matching {fine.expected_plate}. The fine was incorrect and is cleared."
                else:
                    fine.appeal_status = "rejected_by_ai"
                    ai_details = f"I did not detect a match for {fine.expected_plate} in the image. The spot is occupied by a violator."
                ai_msg = FineMessage(fine_id=fine.id, sender="AI Assessor", content=ai_details)
                db.session.add(ai_msg)
            else:
                fine.appeal_status = "pending_human"
                err_msg = FineMessage(fine_id=fine.id, sender="System", content=f"AI failure: {is_fine_wrong}. Escalate to human.")
                db.session.add(err_msg)
            db.session.commit()
            broadcast_sse("fine_updated", fine.to_dict())

# ---------------------------------------------------------------------------
# Portal — User Routes
# ---------------------------------------------------------------------------

@app.route("/portal")
@login_required
def portal():
    if getattr(current_user, 'is_admin', False) or current_user.id == 0:
        return redirect(url_for('dashboard'))

    user_plates = user_plate_values(current_user)

    if _is_demo():
        fines = [f for f in _demo_fines() if normalize_plate(f.expected_plate) in user_plates or normalize_plate(f.detected_plate) in user_plates]
        return render_template("user_portal.html", fines=fines, user_plates=user_plates, is_demo=True)

    fines = []
    if user_plates:
        fines = Fine.query.filter(Fine.expected_plate.in_(user_plates)).order_by(Fine.created_at.desc()).all()
    return render_template("user_portal.html", fines=fines, user_plates=user_plates)

@app.route("/portal/settings", methods=["GET", "POST"])
@login_required
def account_settings():
    if getattr(current_user, "is_admin", False) or current_user.id == 0:
        return redirect(url_for("dashboard"))

    if _is_demo():
        flash("Demo mode — account settings are read-only.", "info")
        return render_template(
            "account_settings.html",
            user_plates=user_plate_values(current_user),
            plate_rows=[],
            is_demo=True,
        )

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add_plate":
            plate = normalize_plate(request.form.get("license_plate", ""))
            proof_file = request.files.get("registration_document")

            if not is_valid_plate(plate):
                flash("Enter a valid license plate with letters and numbers.", "danger")
            elif UserPlate.query.filter_by(plate=plate).first():
                flash("That license plate is already registered to an account.", "danger")
            elif not proof_file or not proof_file.filename:
                flash("Upload a PDF or DOCX registration document from city hall, police, or vehicle registration.", "danger")
            else:
                proof_rel = None
                proof_path = None
                try:
                    proof_rel, mime = save_plate_proof_upload(proof_file)
                    proof_path = os.path.join(app.config["UPLOAD_FOLDER"], proof_rel)
                    verified, reason = verify_plate_registration_document(
                        proof_path,
                        mime,
                        plate,
                        current_user.name,
                    )
                    if verified:
                        db.session.add(
                            UserPlate(
                                user_id=current_user.id,
                                plate=plate,
                                verification_status="approved",
                                verification_document=proof_rel,
                                verification_notes=reason,
                                verified_at=_now(),
                            )
                        )
                        sync_user_primary_plate(current_user)
                        db.session.commit()
                        flash(f"Plate {plate} verified and added.", "success")
                    else:
                        if proof_path and os.path.exists(proof_path):
                            os.remove(proof_path)
                        flash(f"Document did not match your details: {reason}", "danger")
                except ValueError as exc:
                    flash(str(exc), "danger")
                except RuntimeError as exc:
                    if proof_path and os.path.exists(proof_path):
                        db.session.add(
                            UserPlate(
                                user_id=current_user.id,
                                plate=plate,
                                verification_status="pending",
                                verification_document=proof_rel if proof_path else None,
                                verification_notes=str(exc)[:500],
                            )
                        )
                        sync_user_primary_plate(current_user)
                        db.session.commit()
                        flash(
                            "Document uploaded. Automatic verification is unavailable — an admin will review it.",
                            "warning",
                        )
                    else:
                        flash(str(exc), "danger")

        elif action == "remove_plate":
            plate_id = request.form.get("plate_id", type=int)
            row = UserPlate.query.filter_by(id=plate_id, user_id=current_user.id).first()
            if row:
                db.session.delete(row)
                sync_user_primary_plate(current_user)
                db.session.commit()
                flash("License plate removed.", "success")
            else:
                flash("Plate not found.", "danger")

        elif action == "update_profile":
            name = request.form.get("name", "").strip()
            if name:
                current_user.name = name
                db.session.commit()
                flash("Profile updated.", "success")
            else:
                flash("Username cannot be empty.", "danger")

        return redirect(url_for("account_settings"))

    plate_rows = [
        {
            "id": row.id,
            "plate": row.plate,
            "status": row.verification_status,
            "notes": row.verification_notes,
        }
        for row in current_user.plates.order_by(UserPlate.created_at.desc())
    ]
    return render_template(
        "account_settings.html",
        user_plates=user_plate_values(current_user),
        plate_rows=plate_rows,
    )


@app.route("/portal/fine/<int:fine_id>/request-photo", methods=["POST"])
@login_required
def request_photo(fine_id):
    if _is_demo():
        flash("Demo mode — photo request not sent.", "info")
        return redirect(url_for("portal"))
    fine = Fine.query.get_or_404(fine_id)
    
    if not user_owns_plate(current_user, fine.expected_plate):
        abort(403)
        
    if not fine.photo_requested:
        fine.photo_requested = True
        db.session.commit()
        flash("Photo evidence requested. You will receive an email shortly.", "success")
        
    return redirect(url_for("portal"))


@app.route("/portal/fine/<int:fine_id>/appeal", methods=["POST"])
@login_required
def appeal_fine(fine_id):
    if _is_demo():
        flash("Demo mode — appeal not submitted.", "info")
        return redirect(url_for("portal"))
    fine = Fine.query.get_or_404(fine_id)
    
    if not user_owns_plate(current_user, fine.expected_plate):
        abort(403)
        
    reason = request.form.get("reason", "I am appealing this fine.")
    
    # Store user message
    user_msg = FineMessage(fine_id=fine.id, sender=current_user.name, content=reason)
    db.session.add(user_msg)
        
    if fine.appeal_status == "none":
        fine.appeal_status = "pending_ai"
        flash("Appeal submitted. The AI is analyzing the evidence (this may take a moment)...", "info")
        success, is_fine_wrong = analyze_appeal_with_ollama(fine)
        
        if success:
            ai_details = ""
            if is_fine_wrong:
                fine.appeal_status = "approved"
                fine.resolved = True
                ai_details = f"I detected plate matching {fine.expected_plate}. The fine was incorrect and is cleared."
                flash("AI Analysis: the fine was incorrect and has been cleared.", "success")
            else:
                fine.appeal_status = "rejected_by_ai"
                ai_details = f"I did not detect a match for {fine.expected_plate} in the image. The spot is occupied by a violator."
                flash("AI Analysis: the fine is valid based on the evidence.", "danger")
            
            ai_msg = FineMessage(fine_id=fine.id, sender="AI Assessor", content=ai_details)
            db.session.add(ai_msg)
        else:
            fine.appeal_status = "pending_human"
            flash(f"AI could not process appeal. Forwarded to admin.", "warning")
            err_msg = FineMessage(fine_id=fine.id, sender="System", content=f"AI failure: {is_fine_wrong}. Escalate to human.")
            db.session.add(err_msg)
            
        db.session.commit()
        
    elif fine.appeal_status == "rejected_by_ai":
        # Second appeal -> Human admin
        fine.appeal_status = "pending_human"
        fine.appeal_reason = reason
        db.session.commit()
        flash("Your second appeal has been forwarded to a human administrator.", "success")
        
    return redirect(url_for("portal"))


@app.route("/admin/fine/<int:fine_id>/appeal/<action>", methods=["POST"])
@require_admin
def admin_handle_appeal(fine_id, action):
    if _is_demo():
        flash("Demo mode — no changes are saved.", "info")
        return redirect(request.referrer or url_for("dashboard"))
    fine = Fine.query.get_or_404(fine_id)
    admin_reason = request.form.get("admin_reason", "")
    
    if action == "approve":
        fine.appeal_status = "approved"
        fine.resolved = True
        msg = f"Appeal approved. Fine resolved. {admin_reason}"
        flash("Appeal approved. Fine resolved.", "success")
    elif action == "reject":
        fine.appeal_status = "rejected_human"
        msg = f"Appeal rejected permanently. {admin_reason}"
        flash("Appeal rejected.", "danger")
        
    admin_msg = FineMessage(fine_id=fine.id, sender="Admin", content=msg)
    db.session.add(admin_msg)
    db.session.commit()
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/fine/<int:fine_id>/chat", methods=["POST"])
@login_required
def add_chat_message(fine_id):
    if _is_demo():
        flash("Demo mode — no changes are saved.", "info")
        return redirect(request.referrer or url_for("portal" if not current_user.is_admin else "dashboard"))
    fine = Fine.query.get_or_404(fine_id)
    if not current_user.is_admin and not user_owns_plate(current_user, fine.expected_plate):
        abort(403)
        
    content = request.form.get("message", "").strip()
    if not content and "attachment" not in request.files:
        flash("Message or attachment required.", "warning")
        return redirect(request.referrer)
        
    attachment_filename = None
    if "attachment" in request.files:
        f = request.files["attachment"]
        if f.filename:
            safe_name = secure_filename(f"chat_{_now().strftime('%Y%m%d_%H%M%S')}_{f.filename}")
            f.save(os.path.join(app.config["UPLOAD_FOLDER"], safe_name))
            attachment_filename = safe_name
            
    sender = "Admin" if current_user.is_admin else current_user.name
    msg = FineMessage(fine_id=fine.id, sender=sender, content=content, attachment_filename=attachment_filename)
    db.session.add(msg)
    db.session.commit()
    
    broadcast_sse("fine_updated", fine.to_dict())
    return redirect(request.referrer)

sse_clients = []

def broadcast_sse(event_type, data):
    msg = json.dumps({"type": event_type, "data": data})
    for q in list(sse_clients):
        try:
            q.put(msg)
        except:
            pass

@app.route("/stream")
@login_required
def stream():
    def event_stream():
        q = queue.Queue()
        sse_clients.append(q)
        try:
            while True:
                msg = q.get()
                yield f"data: {msg}\n\n"
        finally:
            if q in sse_clients:
                sse_clients.remove(q)
    return Response(event_stream(), content_type="text/event-stream")

@app.route("/portal/fine/<int:fine_id>/receipt", methods=["GET"])
@login_required
def receipt(fine_id):
    if _is_demo():
        fine = next((f for f in _demo_fines() if f.id == fine_id), None)
        if not fine:
            abort(404)
    else:
        fine = Fine.query.get_or_404(fine_id)
        if not user_owns_plate(current_user, fine.expected_plate):
            abort(403)
        
    # Super simple printable view
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>ParkScan Receipt - {fine.id}</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; padding: 40px; color: #333; }}
            .header {{ font-size: 24px; font-weight: bold; margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
            .details {{ margin-bottom: 30px; line-height: 1.6; }}
            .stamp {{ display: inline-block; padding: 10px 20px; border: 3px solid #4CAF50; color: #4CAF50; font-weight: bold; font-size: 20px; border-radius: 8px; transform: rotate(-5deg); margin-top: 20px; }}
            @media print {{ body {{ padding: 0; }} }}
        </style>
    </head>
    <body onload="window.print()">
        <div class="header">ParkScan - Official Resolution Receipt</div>
        <div class="details">
            <p><strong>Driver Name:</strong> {current_user.name}</p>
            <p><strong>Expected Plate:</strong> {fine.expected_plate}</p>
            <p><strong>Incident Date:</strong> {fine.created_at.strftime('%Y-%m-%d %H:%M:%S') if fine.created_at else 'Unknown'}</p>
            <p><strong>Status:</strong> { 'RESOLVED' if fine.resolved else 'PENDING' }</p>
            <p><strong>Appeal Reason / Summary:</strong> { fine.appeal_reason or 'No specific appeal context' }</p>
            <p>This report serves as formal proof that the ticket #{fine.id} was analyzed by our systems.</p>
        </div>
        """
    if fine.resolved:
        html += '<div class="stamp">OFFICIALLY RESOLVED</div>'
        
    html += "</body></html>"
    return html

# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template("404.html"), 403

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"\n  ParkWatch Server starting on http://0.0.0.0:{config.PORT}\n")
    app.run(host="0.0.0.0", port=config.PORT, debug=True)
