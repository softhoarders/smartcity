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
from models import (
    db, Device, Fine, User, UserPlate, PushSubscription, FineMessage,
    SpotListing, SpotBooking, SpotTransaction, SpotActivityLog,
    WalletWithdrawal,
)
import spots_service
import activity_log
import pricing_engine
import spot_prices
import promo_service
import receipt_pdf
import find_parking_service
import demo_parking_data
from geo_context import geocode_search
from mailer import mail, PhotoMailerWorker
from plate_document_verifier import verify_plate_registration_document, normalize_plate_for_claim
import json
import n8n_events
from n8n_routes import n8n_bp
import security
import two_factor
from pywebpush import webpush, WebPushException

# VAPID Config
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_CLAIMS = {
    "sub": os.getenv("VAPID_SUBJECT", "mailto:admin@spotflow.com")
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
app.register_blueprint(n8n_bp)
security.configure_session_cookies(app)


@app.after_request
def _apply_security_headers(response):
    return security.apply_security_headers(response)

@app.context_processor
def inject_globals():
    ctx = {
        "format_spots": spot_prices.format_tenths,
        "currency_name": config.WALLET_CURRENCY_NAME,
        "currency_singular": config.WALLET_CURRENCY_SINGULAR,
    }
    if current_user.is_authenticated:
        ctx["is_demo"] = _is_demo()
        if not getattr(current_user, "is_admin", False) and current_user.id != 0:
            bal = 0
            if _is_demo():
                bal = _demo_wallet_balance()
                ctx["nav_spots_balance"] = bal
            elif current_user.id > 0:
                try:
                    bal = spots_service.user_balance(current_user)
                    ctx["nav_spots_balance"] = bal
                except Exception:
                    bal = 0
                    ctx["nav_spots_balance"] = 0
            if bal < config.LOW_BALANCE_THRESHOLD:
                ctx["low_balance_warning"] = True
                ctx["low_balance_threshold"] = config.LOW_BALANCE_THRESHOLD
    return ctx

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

    user_spots_columns = {
        "spots_balance": "INTEGER NOT NULL DEFAULT 0",
        "subscription_active": "BOOLEAN NOT NULL DEFAULT 0",
        "subscription_started_at": "DATETIME",
        "subscription_next_billing_at": "DATETIME",
    }
    for column_name, column_sql in user_spots_columns.items():
        if column_name not in user_columns:
            db.session.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_sql}"))

    twofa_columns = {
        "twofa_enabled": "BOOLEAN NOT NULL DEFAULT 0",
        "twofa_secret": "VARCHAR(64)",
    }
    for column_name, column_sql in twofa_columns.items():
        if column_name not in user_columns:
            db.session.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_sql}"))

    payout_columns = {
        "payout_account_holder": "VARCHAR(120)",
        "payout_iban": "VARCHAR(34)",
        "payout_bank_name": "VARCHAR(120)",
        "referred_by_code": "VARCHAR(32)",
    }
    for column_name, column_sql in payout_columns.items():
        if column_name not in user_columns:
            db.session.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_sql}"))

    if "owner_user_id" not in device_columns:
        db.session.execute(text("ALTER TABLE devices ADD COLUMN owner_user_id INTEGER"))

    db.session.commit()
    db.create_all()
    inspector = inspect(db.engine)

    listing_columns = set()
    if inspector.has_table("spot_listings"):
        listing_columns = {c["name"] for c in inspector.get_columns("spot_listings")}
    listing_migrations = {
        "instant_price_tenths": "INTEGER",
        "schedule_price_tenths": "INTEGER",
        "schedule_deposit_tenths": "INTEGER",
        "pricing_mode": "VARCHAR(20) NOT NULL DEFAULT 'manual'",
        "owner_min_tenths": f"INTEGER NOT NULL DEFAULT {config.PRICING_DEFAULT_MIN_TENTHS}",
        "owner_max_tenths": f"INTEGER NOT NULL DEFAULT {config.PRICING_DEFAULT_MAX_TENTHS}",
        "suggested_instant_tenths": "INTEGER",
        "suggested_schedule_tenths": "INTEGER",
        "dynamic_instant_tenths": "INTEGER",
        "dynamic_schedule_tenths": "INTEGER",
        "location_zone": "VARCHAR(30)",
        "pricing_reason": "VARCHAR(500)",
        "last_priced_at": "DATETIME",
    }
    for col, sql in listing_migrations.items():
        if col not in listing_columns:
            db.session.execute(text(f"ALTER TABLE spot_listings ADD COLUMN {col} {sql}"))

    db.session.commit()

    for listing in SpotListing.query.all():
        if not listing.instant_price_tenths:
            listing.instant_price_tenths = (listing.instant_price_per_hour or 10) * 100
        elif listing.instant_price_tenths < 1000:
            listing.instant_price_tenths *= 10
        if not listing.schedule_price_tenths:
            listing.schedule_price_tenths = (listing.schedule_price_per_hour or 8) * 100
        elif listing.schedule_price_tenths < 1000:
            listing.schedule_price_tenths *= 10
        if not listing.schedule_deposit_tenths:
            listing.schedule_deposit_tenths = (listing.schedule_deposit_spots or 5) * 100
        elif listing.schedule_deposit_tenths < 1000:
            listing.schedule_deposit_tenths *= 10
        if not listing.owner_min_tenths:
            listing.owner_min_tenths = config.PRICING_DEFAULT_MIN_TENTHS * 10
        elif listing.owner_min_tenths < 1000:
            listing.owner_min_tenths *= 10
        if not listing.owner_max_tenths:
            listing.owner_max_tenths = config.PRICING_DEFAULT_MAX_TENTHS * 10
        elif listing.owner_max_tenths < 1000:
            listing.owner_max_tenths *= 10
    db.session.commit()

    tx_columns = set()
    if inspector.has_table("spot_transactions"):
        tx_columns = {c["name"] for c in inspector.get_columns("spot_transactions")}
    if "receipt_token" not in tx_columns:
        db.session.execute(text("ALTER TABLE spot_transactions ADD COLUMN receipt_token VARCHAR(64)"))
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    for col, sql in {
        "payout_account_holder": "VARCHAR(120)",
        "payout_iban": "VARCHAR(34)",
        "payout_bank_name": "VARCHAR(120)",
        "referred_by_code": "VARCHAR(32)",
    }.items():
        if col not in user_columns:
            db.session.execute(text(f"ALTER TABLE users ADD COLUMN {col} {sql}"))
    db.session.commit()
    db.create_all()
    try:
        promo_service.ensure_default_promos()
    except Exception:
        pass

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


def _periodic_pricing_refresh():
    import time
    while True:
        time.sleep(config.PRICING_REFRESH_INTERVAL_SECONDS)
        try:
            with app.app_context():
                n = pricing_engine.refresh_all_active_listings()
                if n:
                    activity_log.log_activity("pricing.batch_refresh", metadata={"count": n}, commit=True)
        except Exception as exc:
            print(f"[pricing] refresh error: {exc}")


threading.Thread(target=_periodic_pricing_refresh, daemon=True).start()


@app.after_request
def _auto_log_portal_activity(response):
    try:
        if request.method != "GET":
            return response
        page = activity_log.AUTO_LOG_GET_ENDPOINTS.get(request.endpoint or "")
        if not page:
            return response
        if not current_user.is_authenticated or getattr(current_user, "is_admin", False):
            return response
        if current_user.id <= 0 or _is_demo():
            return response
        activity_log.log_activity(
            f"page.view.{page}",
            user_id=current_user.id,
            metadata={"path": request.path},
            commit=True,
        )
    except Exception:
        pass
    return response

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
        demo_user.name = _demo_profile_name()
        demo_user.plate_list = _demo_plate_values()
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
    """Demo sample data only when explicitly signed in via demo / demo123!."""
    return bool(session.get("is_demo", False))


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


def _portal_stats(fines):
    """Summary counts for the driver home screen."""
    resolved = sum(1 for f in fines if getattr(f, "resolved", False))
    total = len(fines)
    open_count = total - resolved
    action_count = 0
    pending_count = 0
    for f in fines:
        if getattr(f, "resolved", False):
            continue
        appeal = getattr(f, "appeal_status", "none") or "none"
        if appeal in ("pending_human", "pending_ai"):
            pending_count += 1
            continue
        photo_sent = bool(getattr(f, "photo_sent_at", None))
        photo_requested = bool(getattr(f, "photo_requested", False))
        if (not photo_sent and not photo_requested) or (
            photo_sent and appeal in ("none", "rejected_by_ai")
        ):
            action_count += 1
    return {
        "total": total,
        "open": open_count,
        "resolved": resolved,
        "action": action_count,
        "pending": pending_count,
    }


def _sort_demo_fines(fines):
    appeal_rank = {
        "pending_human": 0,
        "pending_ai": 1,
        "rejected_by_ai": 2,
        "none": 3,
        "rejected_human": 4,
        "approved": 5,
        "rejected": 6,
    }

    def key(f):
        return (
            0 if not f.resolved else 1,
            appeal_rank.get(f.appeal_status, 9),
            -(f.created_at.timestamp() if f.created_at else 0),
        )

    return sorted(fines, key=key)


def _demo_devices():
    return demo_parking_data.build_demo_devices(_now)


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
        # Demo driver (B-123-MAB) — rich alert variety for portal showcase
        make_fine(13, 101, "B-777-THF", "B-123-MAB", 8, confidence=96.4, hours_ago=0.25),
        make_fine(14, 101, "B-123-MAB", "B-123-MAB", 14, confidence=99.1, hours_ago=0.75),
        make_fine(15, 101, "B-450-RVN", "B-123-MAB", 33, confidence=91.0, photo_sent=True, hours_ago=1.5),
        make_fine(16, 101, "B-331-KIO", "B-123-MAB", 72, appeal="pending_ai", confidence=88.3, photo_sent=True, hours_ago=3.5),
        make_fine(17, 101, "B-902-LUX", "B-123-MAB", 120, appeal="rejected_by_ai", confidence=85.7, photo_sent=True, hours_ago=7),
        make_fine(18, 101, "B-144-NXT", "B-123-MAB", 56, appeal="rejected_human", confidence=90.5, photo_sent=True, hours_ago=9),
        make_fine(19, 101, "B-515-OLD", "B-123-MAB", 240, resolved=True, appeal="approved", confidence=87.2, photo_sent=True, hours_ago=36),
        make_fine(20, 101, "B-220-SFT", "B-123-MAB", 19, resolved=True, confidence=97.8, hours_ago=14),
        make_fine(21, 113, "B-888-STR", "B-123-MAB", 27, confidence=92.4, photo_requested=True, hours_ago=2.2),
        make_fine(22, 113, "B-123-MAB", "B-123-MAB", 6, confidence=98.6, hours_ago=0.4),
        make_fine(23, 105, "B-123-MAB", "B-441-PKR", 11, confidence=93.0, hours_ago=1.1),
        make_fine(24, 101, "B-642-FST", "B-123-MAB", 4, confidence=82.1, hours_ago=0.15),
        make_fine(25, 101, "B-190-ZEN", "B-123-MAB", 98, appeal="pending_human", confidence=89.9, photo_sent=True, hours_ago=5.5),
        make_fine(26, 101, "B-505-MID", "B-123-MAB", 41, confidence=86.2, hours_ago=4.2),
        make_fine(27, 101, "B-760-MAX", "B-123-MAB", 156, resolved=True, confidence=94.0, hours_ago=52),
        make_fine(28, 113, "B-404-NTF", "B-123-MAB", 17, confidence=88.8, photo_sent=True, hours_ago=2.8),
    ]

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
        mu(6, "Admin",             "admin@spotflow.ro",           "",           "admin",  "approved", 90),
    ]
    users[2].verification_document = "demo_id_elena.jpg"
    users[3].verification_document = "demo_registration_radu.pdf"
    return users


def _demo_profile_name() -> str:
    return (session.get("demo_profile") or {}).get("name") or "Demo User"


def _demo_plates_state() -> dict:
    state = session.get("demo_plates")
    if state is None:
        state = {"extra": [], "next_id": 100}
        session["demo_plates"] = state
    return state


def _demo_plate_rows():
    from types import SimpleNamespace

    base = _now()
    rows = [
        SimpleNamespace(
            id=1,
            plate="B123MAB",
            status="approved",
            notes="Matched registration document (auto-verified).",
            verified_at=base - timedelta(days=40),
            verification_document="demo_registration_b123mab.pdf",
        ),
    ]
    for raw in _demo_plates_state().get("extra", []):
        rows.append(
            SimpleNamespace(
                id=raw["id"],
                plate=raw["plate"],
                status=raw.get("status", "approved"),
                notes=raw.get("notes", ""),
                verified_at=datetime.fromisoformat(raw["verified_at"])
                if raw.get("verified_at")
                else base,
                verification_document=raw.get("verification_document"),
            )
        )
    return rows


def _demo_plate_values() -> list[str]:
    plates = []
    for row in _demo_plate_rows():
        if row.status == "approved":
            plates.append(row.plate)
    return list(dict.fromkeys(plates))


def _account_owner_name(user) -> str:
    if _is_demo() and getattr(user, "id", None) == -2:
        return _demo_profile_name()
    return (getattr(user, "name", "") or "").strip()


def _process_plate_registration_upload(user, plate_input: str, proof_file, *, demo: bool) -> bool:
    """Validate document with Gemini and add plate. Sets flash messages; caller should redirect."""
    plate = normalize_plate(plate_input)
    owner_name = _account_owner_name(user)

    if not is_valid_plate(plate):
        flash("Enter a valid license plate with letters and numbers.", "danger")
        return True
    if not owner_name or len(owner_name) < 2:
        flash("Set your full name under Profile before uploading a registration document.", "danger")
        return True

    if demo:
        existing = {normalize_plate(r.plate) for r in _demo_plate_rows()}
    else:
        existing = {row.plate for row in user.plates}
    if plate in existing:
        flash("That license plate is already on your account.", "danger")
        return True
    if not demo and UserPlate.query.filter_by(plate=plate).first():
        flash("That license plate is already registered to an account.", "danger")
        return True

    if not proof_file or not proof_file.filename:
        flash(
            "Upload a PDF or Word document (city hall, police, or vehicle registration).",
            "danger",
        )
        return True

    proof_rel = None
    proof_path = None
    try:
        proof_rel, mime = save_plate_proof_upload(proof_file)
        proof_path = os.path.join(app.config["UPLOAD_FOLDER"], proof_rel)
        result = verify_plate_registration_document(proof_path, mime, plate, owner_name)

        if result.verified:
            if demo:
                state = _demo_plates_state()
                state["extra"].insert(
                    0,
                    {
                        "id": state.get("next_id", 100),
                        "plate": plate,
                        "status": "approved",
                        "notes": result.reason[:500],
                        "verified_at": _now().isoformat(),
                        "verification_document": proof_rel,
                    },
                )
                state["next_id"] = state.get("next_id", 100) + 1
                session["demo_plates"] = state
                session.modified = True
            else:
                db.session.add(
                    UserPlate(
                        user_id=user.id,
                        plate=plate,
                        verification_status="approved",
                        verification_document=proof_rel,
                        verification_notes=result.reason[:500],
                        verified_at=_now(),
                    )
                )
                sync_user_primary_plate(user)
                db.session.commit()
                n8n_events.on_plate_verification(user, plate, "approved", result.reason)
            flash(f"Plate {plate} verified and added.", "success")
            return True

        if proof_path and os.path.exists(proof_path):
            os.remove(proof_path)
        flash(f"Document did not match your details: {result.reason}", "danger")
        return True

    except ValueError as exc:
        flash(str(exc), "danger")
        return True
    except RuntimeError as exc:
        if not demo and proof_path and proof_rel:
            db.session.add(
                UserPlate(
                    user_id=user.id,
                    plate=plate,
                    verification_status="pending",
                    verification_document=proof_rel,
                    verification_notes=str(exc)[:500],
                )
            )
            sync_user_primary_plate(user)
            db.session.commit()
            n8n_events.on_plate_verification(user, plate, "pending", str(exc)[:500])
            flash(
                "Document uploaded. Automatic verification is unavailable — an admin will review it.",
                "warning",
            )
        else:
            if proof_path and os.path.exists(proof_path):
                os.remove(proof_path)
            flash(
                f"Could not verify the document automatically: {exc}",
                "danger",
            )
        return True


def _demo_wallet_transactions():
    from types import SimpleNamespace
    base = _now()
    return [
        SimpleNamespace(
            amount=config.SUBSCRIPTION_MONTHLY_SPOTS,
            description="Monthly subscription credit",
            created_at=base - timedelta(days=12),
        ),
        SimpleNamespace(
            amount=50,
            description="Top-up · card ending 4242",
            created_at=base - timedelta(days=18),
        ),
        SimpleNamespace(
            amount=-16,
            description="Instant book · P2-04 · 2h",
            created_at=base - timedelta(days=3),
        ),
        SimpleNamespace(
            amount=-6,
            description="Schedule deposit · H-22",
            created_at=base - timedelta(days=1),
        ),
    ]


def _demo_wallet_state():
    state = session.get("demo_wallet")
    if state is None:
        state = {"balance": 120, "extra_txs": [], "subscription_active": True}
        session["demo_wallet"] = state
    return state


def _demo_wallet_balance():
    return int(_demo_wallet_state().get("balance", 120))


def _demo_wallet_transactions_merged():
    from types import SimpleNamespace

    txs = list(_demo_wallet_transactions())
    for raw in _demo_wallet_state().get("extra_txs", []):
        txs.append(
            SimpleNamespace(
                amount=raw["amount"],
                description=raw["description"],
                created_at=datetime.fromisoformat(raw["created_at"]),
                receipt_token=raw.get("receipt_token"),
                id=raw.get("id"),
            )
        )
    txs.sort(key=lambda t: t.created_at, reverse=True)
    return txs[:25]


def _demo_wallet_credit(amount: int, description: str, *, receipt_token: str | None = None) -> None:
    state = _demo_wallet_state()
    state["balance"] = int(state.get("balance", 120)) + amount
    tx = {
        "amount": amount,
        "description": description,
        "created_at": _now().isoformat(),
    }
    if receipt_token:
        tx["receipt_token"] = receipt_token
    state.setdefault("extra_txs", []).insert(0, tx)
    session["demo_wallet"] = state
    session.modified = True


def _demo_wallet_debit(amount: int, description: str, *, receipt_token: str | None = None) -> None:
    state = _demo_wallet_state()
    bal = int(state.get("balance", 120))
    if bal < amount:
        raise ValueError(f"Insufficient {config.WALLET_CURRENCY_NAME.lower()} balance")
    state["balance"] = bal - amount
    tx = {
        "amount": -amount,
        "description": description,
        "created_at": _now().isoformat(),
    }
    if receipt_token:
        tx["receipt_token"] = receipt_token
    state.setdefault("extra_txs", []).insert(0, tx)
    session["demo_wallet"] = state
    session.modified = True


def _demo_bookings_state() -> list:
    state = _demo_wallet_state()
    bookings = state.get("bookings")
    if bookings is None:
        bookings = []
        state["bookings"] = bookings
        session["demo_wallet"] = state
    return bookings


def _validate_mock_card(card_number: str, card_expiry: str, card_cvc: str) -> str | None:
    digits = re.sub(r"\D", "", card_number or "")
    if len(digits) < 13:
        return "Enter a valid card number."
    cvc = re.sub(r"\D", "", card_cvc or "")
    if len(cvc) < 3:
        return "Enter a valid CVC."
    expiry = (card_expiry or "").strip()
    if not re.match(r"^\d{2}/\d{2}$", expiry):
        return "Use MM/YY for expiry."
    month = int(expiry[:2])
    if month < 1 or month > 12:
        return "Expiry month must be between 01 and 12."
    return None


def _card_last4(card_number: str) -> str:
    digits = re.sub(r"\D", "", card_number or "")
    return digits[-4:] if len(digits) >= 4 else "0000"


def _demo_rental_listings():
    devices = _demo_devices()
    return demo_parking_data.build_demo_rental_listings(devices, _now)


def _is_low_balance(balance: int) -> bool:
    return int(balance) < config.LOW_BALANCE_THRESHOLD


def _demo_apply_promo_bonus(base_spots: int, code: str) -> int:
    norm = promo_service.normalize_code(code)
    demo_promos = {
        "WELCOME10": max(1, base_spots // 10),
        "SPOTFLOW15": max(1, (base_spots * 15) // 100),
        "PARK20": 20,
    }
    if norm not in demo_promos:
        raise ValueError("Promo code not found or inactive.")
    return demo_promos[norm]


def _find_parking_search_redirect_args(item, *, booking_confirmation: dict):
    """Preserve search context and pass booking confirmation query params."""
    args = {}

    def _param(name, type_fn=str):
        raw = request.values.get(name)
        if raw is None or raw == "":
            return None
        try:
            return type_fn(raw)
        except (TypeError, ValueError):
            return None

    lat = _param("lat", float)
    lng = _param("lng", float)
    if lat is not None and lng is not None:
        args["lat"] = lat
        args["lng"] = lng
        args["q"] = _param("q") or _param("label") or ""
    max_dist = _param("max_distance", float)
    args["max_distance"] = max_dist if max_dist is not None else config.FIND_PARKING_RADIUS_KM
    for key in ("sort", "min_price", "max_price", "status", "booking_mode"):
        val = _param(key)
        if val is not None and val != "":
            args[key] = val
    args["booking_ok"] = "1"
    args["booking_spot"] = booking_confirmation.get("spot", "")
    args["booking_plate"] = booking_confirmation.get("plate", "")
    args["booking_total"] = str(booking_confirmation.get("total", ""))
    args["booking_hours"] = str(booking_confirmation.get("hours", ""))
    args["booking_status"] = booking_confirmation.get("status", "")
    args["booking_type"] = booking_confirmation.get("type", "instant")
    if booking_confirmation.get("starts"):
        args["booking_starts"] = booking_confirmation["starts"]
    if booking_confirmation.get("ends"):
        args["booking_ends"] = booking_confirmation["ends"]
    return args


def _render_find_parking_page(listings, user_plates, balance, renter_bookings, *, is_demo: bool, search: dict | None = None):
    center_lat = float((search or {}).get("lat") or config.BUCHAREST_CENTER_LAT)
    center_lng = float((search or {}).get("lng") or config.BUCHAREST_CENTER_LNG)
    search_label = (search or {}).get("label") or "Bucharest city center"

    sort = request.args.get("sort", "relevance")
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    max_distance = request.args.get("max_distance", type=float)
    if max_distance is None and (search or {}).get("lat"):
        max_distance = config.FIND_PARKING_RADIUS_KM
    status_filter = request.args.get("status") or None
    booking_mode = request.args.get("booking_mode") or None

    booking_confirmation = None
    if request.args.get("booking_ok"):
        booking_confirmation = {
            "spot": request.args.get("booking_spot", ""),
            "plate": request.args.get("booking_plate", ""),
            "total": request.args.get("booking_total", ""),
            "hours": request.args.get("booking_hours", ""),
            "status": request.args.get("booking_status", ""),
            "type": request.args.get("booking_type", "instant"),
            "starts": request.args.get("booking_starts", ""),
            "ends": request.args.get("booking_ends", ""),
        }

    filtered = find_parking_service.filter_and_sort_listings(
        listings,
        center_lat,
        center_lng,
        min_price=min_price,
        max_price=max_price,
        max_distance_km=max_distance,
        booking_mode=booking_mode,
        status_filter=status_filter,
        sort=sort,
    )
    recommended = find_parking_service.top_recommendations(filtered, 3)
    rec_ids = {item["listing"].id for item in recommended}
    rest = [item for item in filtered if item["listing"].id not in rec_ids]

    return render_template(
        "find_parking.html",
        listings=rest,
        recommended=recommended,
        all_listings=filtered,
        user_plates=user_plates,
        balance=balance,
        renter_bookings=renter_bookings,
        mapped=any(item["device"].latitude for item in filtered),
        is_demo=is_demo,
        search_center={"lat": center_lat, "lng": center_lng, "label": search_label},
        low_balance=_is_low_balance(balance),
        low_balance_threshold=config.LOW_BALANCE_THRESHOLD,
        filters={
            "sort": sort,
            "min_price": min_price,
            "max_price": max_price,
            "max_distance": max_distance,
            "status": status_filter,
            "booking_mode": booking_mode,
        },
        search_radius_km=config.FIND_PARKING_RADIUS_KM,
        booking_confirmation=booking_confirmation,
    )


def _demo_owned_spots():
    from types import SimpleNamespace
    devices = {d.id: d for d in _demo_devices()}
    device = devices[101]
    listing = SimpleNamespace(
        id=99,
        is_active=True,
        approval_mode="manual",
        pricing_mode="auto",
        description="Rent when you're at the office.",
        location_zone="Calea Victoriei",
        owner_min_tenths=50,
        owner_max_tenths=300,
        instant_price_tenths=80,
        schedule_price_tenths=60,
        instant_price_per_hour=8,
        schedule_price_per_hour=6,
        schedule_deposit_spots=5,
    )
    pending = SimpleNamespace(
        id=501,
        status="pending_approval",
        renter_plate="IF-22-RST",
        starts_at=_now() + timedelta(hours=5),
        ends_at=_now() + timedelta(hours=9),
        total_spots=24,
    )
    return [{
        "device": device,
        "listing": listing,
        "pending": [pending],
        "instant_display": "8",
        "schedule_display": "6",
    }]


def _demo_renter_bookings():
    from types import SimpleNamespace

    base = _now()
    devices = {d.id: d for d in _demo_devices()}
    rows = [
        SimpleNamespace(
            listing=SimpleNamespace(device=devices.get(105) or _demo_devices()[0]),
            renter_plate="B123MAB",
            starts_at=base - timedelta(hours=1),
            ends_at=base + timedelta(hours=1),
            booking_type="instant",
            status="active",
        ),
    ]
    for raw in _demo_bookings_state():
        dev = devices.get(raw.get("device_id"))
        if not dev:
            continue
        rows.insert(
            0,
            SimpleNamespace(
                listing=SimpleNamespace(device=dev, id=raw.get("listing_id")),
                renter_plate=raw.get("plate", "B123MAB"),
                starts_at=datetime.fromisoformat(raw["starts_at"]),
                ends_at=datetime.fromisoformat(raw["ends_at"]),
                booking_type=raw.get("booking_type", "instant"),
                status=raw.get("status", "active"),
            ),
        )
    return rows[:20]


def _demo_process_find_parking_post(user_plates: list[str]):
    from types import SimpleNamespace

    listing_id = request.form.get("listing_id", type=int)
    items = _demo_rental_listings()
    item = next((x for x in items if x["listing"].id == listing_id), None)
    if not item:
        flash("Listing not found.", "danger")
        return redirect(url_for("find_parking"))

    listing = item["listing"]
    renter_plate = normalize_plate(request.form.get("renter_plate", ""))
    if renter_plate not in user_plates:
        flash("Select one of your verified plates.", "danger")
        return redirect(url_for("find_parking"))

    action = request.form.get("action")
    try:
        if action == "instant_book":
            hours = request.form.get("hours", type=int) or config.MIN_INSTANT_HOURS
            hours = max(config.MIN_INSTANT_HOURS, min(hours, config.MAX_BOOKING_HOURS))
            total = spot_prices.hundredths_to_billable_spots(item["instant_hundredths"] * hours)
            _demo_wallet_debit(
                total,
                f"Instant book · {item['device'].spot_label} · {hours}h",
            )
            starts = _now()
            ends = starts + timedelta(hours=hours)
            status = "pending_approval" if listing.approval_mode == "manual" else "active"
            _demo_bookings_state().insert(
                0,
                {
                    "listing_id": listing.id,
                    "device_id": item["device"].id,
                    "plate": renter_plate,
                    "starts_at": starts.isoformat(),
                    "ends_at": ends.isoformat(),
                    "booking_type": "instant",
                    "status": status,
                },
            )
            confirm = {
                "spot": item["device"].spot_label,
                "plate": renter_plate,
                "total": total,
                "hours": hours,
                "status": status,
                "type": "instant",
            }
            return redirect(
                url_for("find_parking", **_find_parking_search_redirect_args(item, booking_confirmation=confirm))
            )
        elif action == "schedule_book":
            starts_raw = request.form.get("starts_at", "")
            ends_raw = request.form.get("ends_at", "")
            starts_at = datetime.fromisoformat(starts_raw)
            ends_at = datetime.fromisoformat(ends_raw)
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=timezone.utc)
            hours = max(1, int((ends_at - starts_at).total_seconds() // 3600) or 1)
            total_h = item["schedule_hundredths"] * hours
            deposit_h = min(item["deposit_hundredths"], total_h)
            deposit = spot_prices.hundredths_to_billable_spots(deposit_h)
            _demo_wallet_debit(
                deposit,
                f"Schedule deposit · {item['device'].spot_label}",
            )
            status = "pending_approval" if listing.approval_mode == "manual" else "approved"
            _demo_bookings_state().insert(
                0,
                {
                    "listing_id": listing.id,
                    "device_id": item["device"].id,
                    "plate": renter_plate,
                    "starts_at": starts_at.isoformat(),
                    "ends_at": ends_at.isoformat(),
                    "booking_type": "scheduled",
                    "status": status,
                },
            )
            confirm = {
                "spot": item["device"].spot_label,
                "plate": renter_plate,
                "total": deposit,
                "hours": hours,
                "status": status,
                "type": "scheduled",
                "starts": starts_at.strftime("%d %b %H:%M"),
                "ends": ends_at.strftime("%d %b %H:%M"),
            }
            return redirect(
                url_for("find_parking", **_find_parking_search_redirect_args(item, booking_confirmation=confirm))
            )
        else:
            flash("Unknown action.", "danger")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("find_parking", **request.args.to_dict()))


def _get_device_by_mac(mac):
    return Device.query.filter_by(mac_address=mac).first()


def normalize_plate(plate):
    return re.sub(r"[^A-Z0-9]", "", (plate or "").upper())


def is_valid_plate(plate):
    normalized = normalize_plate(plate)
    return 5 <= len(normalized) <= 10 and any(char.isalpha() for char in normalized) and any(char.isdigit() for char in normalized)


def user_plate_values(user):
    if _is_demo() and getattr(user, "id", None) == -2:
        return _demo_plate_values()
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
        raise ValueError("Upload a PDF or Word document (.pdf, .doc, .docx) from city hall, police, or vehicle registration.")

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
@security.require_device_api_key
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
@security.require_device_api_key
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
    spots_service.refresh_booking_statuses()
    effective_plate = spots_service.effective_assigned_plate(device)
    return jsonify({
        "assigned_plate": effective_plate,
        "owner_plate": device.assigned_plate,
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
@security.require_device_api_key
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

    spots_service.refresh_booking_statuses()
    effective_expected = spots_service.effective_assigned_plate(device)
    if not expected_plate and effective_expected:
        expected_plate = normalize_plate(effective_expected)

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
        expected_plate=expected_plate or normalize_plate(effective_expected or device.assigned_plate or "N/A"),
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
    n8n_events.on_violation_created(fine, device)

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
    if fine.resolved:
        n8n_events.on_violation_resolved(fine)
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
    return render_template("landing.html")

@app.route("/admin")
@require_admin
def dashboard():
    show_all_fines = request.args.get("all") == "1"

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
            show_all_fines=show_all_fines,
            is_demo=True,
        )

    devices = Device.query.order_by(Device.created_at.desc()).all()
    fines_query = Fine.query.order_by(Fine.created_at.desc())
    recent_fines = fines_query.all() if show_all_fines else fines_query.limit(20).all()
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
        show_all_fines=show_all_fines,
        is_demo=False,
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
    return render_template("device_detail.html", device=device, fines=fines, is_demo=False)


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
    if not _is_demo():
        return redirect(url_for("dashboard"))

    devices = _demo_devices()
    fines = _demo_fines()

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
    return render_template("users.html", users=users, is_demo=False)


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
    return redirect(url_for("dashboard", all=1))


@app.route("/fine/<int:fine_id>/resolve", methods=["POST"])
@require_admin
def resolve_fine(fine_id):
    if _is_demo():
        flash("Demo mode — no changes are saved.", "info")
        return redirect(request.referrer or url_for("dashboard"))
    fine = Fine.query.get_or_404(fine_id)
    fine.resolved = not fine.resolved
    db.session.commit()
    if fine.resolved:
        n8n_events.on_violation_resolved(fine)
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

def _pending_2fa_user():
    """Resolve the user awaiting mock email verification."""
    if session.get("pending_2fa_demo"):
        role = session.get("pending_2fa_demo_role", "driver")
        if role == "admin":
            user = User(email="demo", password_hash="", license_plate="", role="admin", verification_status="approved")
            user.id = -1
            user.name = "Demo Admin"
        else:
            user = User(
                email="demo",
                password_hash="",
                license_plate="B-123-MAB",
                role="driver",
                verification_status="approved",
            )
            user.id = -2
            user.name = "Demo User"
            user.plate_list = ["B123MAB"]
        return user
    return User.query.get(session.get("pending_2fa_user_id"))


def _start_mock_login_2fa(user, *, remember=False):
    session["pending_2fa_user_id"] = user.id
    session["pending_2fa_remember"] = remember
    session["pending_2fa_exp"] = (_now() + timedelta(minutes=5)).timestamp()
    session["pending_2fa_email"] = getattr(user, "email", "") or "your email"
    session["pending_2fa_demo"] = user.id < 0
    session["pending_2fa_demo_role"] = "admin" if user.id == -1 else "driver"
    return redirect(url_for("login_2fa"))


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
        login_identifier = request.form.get("email", "").strip()
        email = login_identifier.lower()
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
            if role == "driver":
                referral = request.form.get("referral_code", "")
                if referral:
                    promo_service.redeem_referral_on_signup(user, referral)

            session.pop("is_demo", None)
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

        if not security.login_attempt_allowed():
            flash("Too many sign-in attempts. Please wait a few minutes.", "danger")
            return redirect(url_for("login"))

        user = User.query.filter(db.func.lower(User.email) == email).first()
        if not user and login_identifier:
            user = User.query.filter(db.func.lower(User.name) == email).first()

        is_demo = email == "demo" and password == "demo123!"
        if is_demo:
            if account_type == "admin":
                demo_admin = User(email="demo", password_hash="", license_plate="", role="admin", verification_status="approved")
                demo_admin.id = -1
                demo_admin.name = "Demo Admin"
            else:
                demo_admin = User(
                    email="demo",
                    password_hash="",
                    license_plate="B-123-MAB",
                    role="driver",
                    verification_status="approved",
                )
                demo_admin.id = -2
                demo_admin.name = "Demo User"
                demo_admin.plate_list = ["B123MAB"]
            session.pop("is_demo", None)
            return _start_mock_login_2fa(demo_admin)

        session.pop("is_demo", None)

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
                return _start_mock_login_2fa(user)
        else:
            security.record_failed_login()
            flash("Invalid username, email, or password.", "danger")

    return render_template("user_login.html")


@app.route("/login/2fa", methods=["GET", "POST"])
def login_2fa():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if not security.pending_2fa_valid():
        flash("Verification expired. Please sign in again.", "warning")
        security.clear_pending_2fa()
        return redirect(url_for("login"))

    user = _pending_2fa_user()
    if not user:
        security.clear_pending_2fa()
        return redirect(url_for("login"))

    masked_email = session.get("pending_2fa_email") or user.email or "your email"

    if request.method == "POST":
        if two_factor.verify_mock_login_pin(request.form.get("code", "")):
            remember = bool(session.get("pending_2fa_remember"))
            is_demo = bool(session.get("pending_2fa_demo"))
            security.clear_pending_2fa()
            if is_demo:
                session["is_demo"] = True
            login_user(user, remember=remember)
            flash("Signed in successfully.", "success")
            return redirect(url_for("dashboard") if user.is_admin else url_for("portal"))
        flash("Invalid verification code.", "danger")

    return render_template("login_2fa.html", masked_email=masked_email)


@app.route("/logout")
@login_required
def logout():
    session.pop("is_demo", None)
    session.pop("demo_wallet", None)
    session.pop("demo_plates", None)
    session.pop("demo_profile", None)
    security.clear_pending_2fa()
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
    db.session.flush()
    if config.NEW_USER_WELCOME_SPOTS > 0:
        spots_service.credit_spots(
            user,
            config.NEW_USER_WELCOME_SPOTS,
            "welcome",
            f"Welcome bonus ({config.NEW_USER_WELCOME_SPOTS} {config.WALLET_CURRENCY_NAME})",
        )
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
        portal_mapped = [
            f for f in fines
            if getattr(f, "device", None) and getattr(f.device, "latitude", None) is not None
        ]
        return render_template(
            "user_portal.html",
            fines=fines,
            user_plates=user_plates,
            stats=_portal_stats(fines),
            portal_mapped=portal_mapped,
            is_demo=True,
        )

    fines = []
    if user_plates:
        fines = Fine.query.filter(Fine.expected_plate.in_(user_plates)).order_by(Fine.created_at.desc()).all()
    portal_mapped = [
        f for f in fines
        if f.device and f.device.latitude is not None and f.device.longitude is not None
    ]
    return render_template(
        "user_portal.html",
        fines=fines,
        user_plates=user_plates,
        stats=_portal_stats(fines),
        portal_mapped=portal_mapped,
        is_demo=False,
    )

@app.route("/portal/settings", methods=["GET", "POST"])
@login_required
def account_settings():
    if getattr(current_user, "is_admin", False) or current_user.id == 0:
        return redirect(url_for("dashboard"))

    if _is_demo():
        if request.method == "POST":
            action = request.form.get("action", "")
            if action == "add_plate":
                _process_plate_registration_upload(
                    current_user,
                    request.form.get("license_plate", ""),
                    request.files.get("registration_document"),
                    demo=True,
                )
            elif action == "update_profile":
                name = request.form.get("name", "").strip()
                if name:
                    session["demo_profile"] = {"name": name}
                    session.modified = True
                    flash("Profile updated.", "success")
                else:
                    flash("Username cannot be empty.", "danger")
            elif action == "remove_plate":
                plate_id = request.form.get("plate_id", type=int)
                state = _demo_plates_state()
                before = len(state.get("extra", []))
                state["extra"] = [r for r in state.get("extra", []) if r.get("id") != plate_id]
                if len(state["extra"]) < before:
                    session["demo_plates"] = state
                    session.modified = True
                    flash("License plate removed.", "success")
                else:
                    flash("Plate not found.", "danger")
            return redirect(url_for("account_settings"))

        return render_template(
            "account_settings.html",
            user_plates=user_plate_values(current_user),
            plate_rows=_demo_plate_rows(),
            account_owner_name=_account_owner_name(current_user),
            gemini_configured=bool(config.GEMINI_API_KEY),
            is_demo=True,
        )

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add_plate":
            _process_plate_registration_upload(
                current_user,
                request.form.get("license_plate", ""),
                request.files.get("registration_document"),
                demo=False,
            )

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

        elif action == "enable_2fa":
            if current_user.id <= 0:
                flash("2FA is not available for this account.", "warning")
            else:
                current_user.twofa_secret = two_factor.generate_secret()
                current_user.twofa_enabled = True
                db.session.commit()
                flash("Simulated 2FA enabled. Use the code shown under Account → Security.", "success")

        elif action == "disable_2fa":
            current_user.twofa_enabled = False
            current_user.twofa_secret = None
            db.session.commit()
            flash("Simulated 2FA disabled.", "info")

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
        account_owner_name=_account_owner_name(current_user),
        gemini_configured=bool(config.GEMINI_API_KEY),
        twofa_enabled=bool(getattr(current_user, "twofa_enabled", False)),
        simulated_2fa_code=(
            two_factor.current_code(current_user.twofa_secret)
            if getattr(current_user, "twofa_enabled", False) and current_user.twofa_secret
            else None
        ),
        twofa_seconds_remaining=two_factor.seconds_remaining(),
        is_demo=False,
    )


@app.route("/login/2fa/code", methods=["GET"])
def login_2fa_code():
    if not security.pending_2fa_valid():
        return jsonify({"enabled": False}), 403
    user = User.query.get(session.get("pending_2fa_user_id"))
    if not user or not user.twofa_secret:
        return jsonify({"enabled": False}), 403
    return jsonify({
        "enabled": True,
        "code": two_factor.current_code(user.twofa_secret),
        "seconds_remaining": two_factor.seconds_remaining(),
    })


@app.route("/portal/settings/2fa-code", methods=["GET"])
@login_required
def account_2fa_code():
    if not getattr(current_user, "twofa_enabled", False) or not current_user.twofa_secret:
        return jsonify({"enabled": False})
    return jsonify({
        "enabled": True,
        "code": two_factor.current_code(current_user.twofa_secret),
        "seconds_remaining": two_factor.seconds_remaining(),
    })


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
        n8n_events.on_violation_appeal(fine, fine.appeal_status)
        
    elif fine.appeal_status == "rejected_by_ai":
        # Second appeal -> Human admin
        fine.appeal_status = "pending_human"
        fine.appeal_reason = reason
        db.session.commit()
        n8n_events.on_violation_appeal(fine, "pending_human")
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
    n8n_events.on_violation_appeal(fine, fine.appeal_status)
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/fine/<int:fine_id>/chat", methods=["POST"])
@login_required
def add_chat_message(fine_id):
    if not current_user.is_admin:
        abort(404)
    if _is_demo():
        flash("Demo mode — no changes are saved.", "info")
        return redirect(request.referrer or url_for("dashboard"))
    fine = Fine.query.get_or_404(fine_id)
        
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

def _require_driver_portal():
    if getattr(current_user, "is_admin", False) or current_user.id == 0:
        return redirect(url_for("dashboard"))
    return None


@app.route("/portal/wallet", methods=["GET", "POST"])
@login_required
def wallet():
    denied = _require_driver_portal()
    if denied:
        return denied
    if _is_demo():
        state = _demo_wallet_state()
        if request.method == "POST":
            action = request.form.get("action")
            if action == "subscribe_balance":
                cost = config.SUBSCRIPTION_MONTHLY_LEI
                if _demo_wallet_balance() < cost:
                    flash(f"Need at least {cost} {config.WALLET_CURRENCY_NAME.lower()} on balance.", "danger")
                else:
                    state["balance"] = _demo_wallet_balance() - cost
                    state["subscription_active"] = True
                    _demo_wallet_credit(
                        config.SUBSCRIPTION_MONTHLY_SPOTS,
                        "Monthly subscription (balance)",
                    )
                    flash(
                        f"Subscription activated. {config.SUBSCRIPTION_MONTHLY_SPOTS} "
                        f"{config.WALLET_CURRENCY_NAME.lower()} added to your wallet.",
                        "success",
                    )
                return redirect(url_for("wallet"))
            if action == "withdraw":
                try:
                    holder = request.form.get("account_holder", "").strip()
                    iban = request.form.get("iban", "")
                    bank = request.form.get("bank_name", "")
                    if _demo_wallet_balance() < config.WITHDRAWAL_CREDITS:
                        raise ValueError(
                            f"You need at least {config.WITHDRAWAL_CREDITS} "
                            f"{config.WALLET_CURRENCY_NAME.lower()} to withdraw."
                        )
                    token = receipt_pdf.new_receipt_token()
                    _demo_wallet_debit(
                        config.WITHDRAWAL_CREDITS,
                        f"Bank withdrawal — {config.WITHDRAWAL_LEI} lei (pending)",
                        receipt_token=token,
                    )
                    state.setdefault("withdrawals", []).insert(
                        0,
                        {
                            "status": "pending",
                            "lei": config.WITHDRAWAL_LEI,
                            "holder": holder,
                            "iban": "".join(ch for ch in iban.upper() if ch.isalnum()),
                            "bank": bank,
                            "created_at": _now().isoformat(),
                            "receipt_token": token,
                        },
                    )
                    receipt_pdf.save_receipt(
                        token,
                        "Withdrawal request",
                        [
                            ("Amount", f"{config.WITHDRAWAL_CREDITS} {config.WALLET_CURRENCY_NAME}"),
                            ("Payout", f"{config.WITHDRAWAL_LEI} lei"),
                            ("Status", "Pending (demo)"),
                            ("Account holder", holder),
                            ("IBAN", iban),
                        ],
                    )
                    session["demo_wallet"] = state
                    flash(
                        f"Withdrawal requested. {config.WITHDRAWAL_LEI} lei will be sent to your bank (demo).",
                        "success",
                    )
                except ValueError as exc:
                    flash(str(exc), "danger")
                return redirect(url_for("wallet"))

        txs = _demo_wallet_transactions_merged()
        for tx in txs:
            if not hasattr(tx, "receipt_token"):
                raw = getattr(tx, "__dict__", {})
                tx.receipt_token = raw.get("receipt_token")
        return render_template(
            "wallet.html",
            balance=_demo_wallet_balance(),
            subscription_active=bool(state.get("subscription_active", True)),
            subscription_next_billing=_now() + timedelta(days=18),
            subscription_monthly_lei=config.SUBSCRIPTION_MONTHLY_LEI,
            subscription_monthly_spots=config.SUBSCRIPTION_MONTHLY_SPOTS,
            transactions=txs,
            is_demo=True,
            withdrawal_credits=config.WITHDRAWAL_CREDITS,
            withdrawal_lei=config.WITHDRAWAL_LEI,
            low_balance=_is_low_balance(_demo_wallet_balance()),
            low_balance_threshold=config.LOW_BALANCE_THRESHOLD,
            payout_iban=state.get("payout_iban"),
            referral_code="DEMO-REF",
        )

    spots_service.ensure_user_wallet(current_user)

    if request.method == "POST" and request.form.get("action") == "subscribe_balance":
        try:
            spots_service.activate_subscription(current_user)
            n8n_events.on_wallet_event(
                current_user,
                "subscription_activated",
                config.SUBSCRIPTION_MONTHLY_SPOTS,
                "Monthly subscription activated",
            )
            flash(f"Subscription activated. Monthly {config.WALLET_CURRENCY_NAME.lower()} have been added to your wallet.", "success")
        except ValueError as exc:
            flash(str(exc), "danger")

    txs = (
        SpotTransaction.query.filter_by(user_id=current_user.id)
        .order_by(SpotTransaction.created_at.desc())
        .limit(25)
        .all()
    )
    if request.method == "POST" and request.form.get("action") == "withdraw":
        try:
            spots_service.request_bank_withdrawal(
                current_user,
                account_holder=request.form.get("account_holder", ""),
                iban=request.form.get("iban", ""),
                bank_name=request.form.get("bank_name"),
            )
            flash(
                f"Withdrawal requested. {config.WITHDRAWAL_LEI} lei will be sent to your bank account.",
                "success",
            )
        except ValueError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("wallet"))

    bal = spots_service.user_balance(current_user)
    return render_template(
        "wallet.html",
        balance=bal,
        subscription_active=current_user.subscription_active,
        subscription_next_billing=current_user.subscription_next_billing_at,
        subscription_monthly_lei=config.SUBSCRIPTION_MONTHLY_LEI,
        subscription_monthly_spots=config.SUBSCRIPTION_MONTHLY_SPOTS,
        transactions=txs,
        is_demo=False,
        withdrawal_credits=config.WITHDRAWAL_CREDITS,
        withdrawal_lei=config.WITHDRAWAL_LEI,
        low_balance=_is_low_balance(bal),
        low_balance_threshold=config.LOW_BALANCE_THRESHOLD,
        payout_iban=current_user.payout_iban,
        referral_code=promo_service.get_or_create_referral_code(current_user),
    )


@app.route("/portal/wallet/topup", methods=["GET", "POST"])
@login_required
def wallet_topup():
    denied = _require_driver_portal()
    if denied:
        return denied

    plan = request.args.get("plan") or request.form.get("plan") or ""

    if _is_demo():
        if request.method == "POST":
            card_number = request.form.get("card_number", "")
            card_expiry = request.form.get("card_expiry", "")
            card_cvc = request.form.get("card_cvc", "")
            card_error = _validate_mock_card(card_number, card_expiry, card_cvc)
            if card_error:
                flash(card_error, "danger")
                return redirect(url_for("wallet_topup", plan=plan))

            last4 = _card_last4(card_number)
            if plan == "subscription":
                state = _demo_wallet_state()
                state["subscription_active"] = True
                _demo_wallet_credit(
                    config.SUBSCRIPTION_MONTHLY_SPOTS,
                    f"Subscription · card ending {last4}",
                )
                flash(
                    f"Subscription activated. {config.SUBSCRIPTION_MONTHLY_SPOTS} {config.WALLET_CURRENCY_NAME.lower()} added to your wallet.",
                    "success",
                )
                return redirect(url_for("wallet"))

            lei_amount = request.form.get("lei_amount", type=int) or 0
            if lei_amount < 1 or lei_amount > 5000:
                flash("Enter an amount between 1 and 5000 lei.", "danger")
                return redirect(url_for("wallet_topup", plan=plan))
            token = receipt_pdf.new_receipt_token()
            _demo_wallet_credit(lei_amount, f"Top-up · card ending {last4}", receipt_token=token)
            receipt_pdf.save_receipt(
                token,
                "Wallet top-up",
                [
                    ("Amount", f"{lei_amount} lei → {lei_amount} {config.WALLET_CURRENCY_NAME}"),
                    ("Card", f"···· {last4}"),
                    ("Mode", "Demo checkout"),
                ],
            )
            promo_code = request.form.get("promo_code", "").strip()
            if promo_code:
                try:
                    bonus = _demo_apply_promo_bonus(lei_amount, promo_code)
                    _demo_wallet_credit(bonus, f"Promo {promo_service.normalize_code(promo_code)} bonus")
                    flash(f"Promo applied: +{bonus} {config.WALLET_CURRENCY_NAME.lower()}.", "success")
                except ValueError as exc:
                    flash(str(exc), "warning")
            flash(
                f"Added {lei_amount} {config.WALLET_CURRENCY_NAME.lower()} to your wallet.",
                "success",
            )
            return redirect(url_for("wallet"))

        return render_template(
            "wallet_topup.html",
            plan=plan,
            subscription_monthly_lei=config.SUBSCRIPTION_MONTHLY_LEI,
            subscription_monthly_spots=config.SUBSCRIPTION_MONTHLY_SPOTS,
            is_demo=True,
        )

    if request.method == "POST":
        card_number = request.form.get("card_number", "")
        card_expiry = request.form.get("card_expiry", "")
        card_cvc = request.form.get("card_cvc", "")
        card_error = _validate_mock_card(card_number, card_expiry, card_cvc)
        if card_error:
            flash(card_error, "danger")
            return redirect(url_for("wallet_topup", plan=plan))

        card_number = re.sub(r"\D", "", card_number)

        if plan == "subscription":
            try:
                spots_service.subscribe_with_card_mock(current_user)
                activity_log.log_activity(
                    "wallet.subscription_card",
                    user_id=current_user.id,
                    metadata={"spots": config.SUBSCRIPTION_MONTHLY_SPOTS},
                    commit=True,
                )
                n8n_events.on_wallet_event(
                    current_user,
                    "subscription_card",
                    config.SUBSCRIPTION_MONTHLY_SPOTS,
                    "Subscription via mock card",
                )
                flash(
                    f"Subscription active. {config.SUBSCRIPTION_MONTHLY_SPOTS} {config.WALLET_CURRENCY_NAME.lower()} added to your wallet.",
                    "success",
                )
            except ValueError as exc:
                flash(str(exc), "danger")
            return redirect(url_for("wallet"))

        lei_amount = request.form.get("lei_amount", type=int) or 0
        try:
            added = spots_service.mock_topup(current_user, lei_amount)
            token = spots_service.attach_receipt_to_last_transaction(
                current_user,
                "topup",
                "Wallet top-up",
                [
                    ("Amount", f"{lei_amount} lei → {added} {config.WALLET_CURRENCY_NAME}"),
                    ("Payment", "Mock card"),
                ],
            )
            activity_log.log_activity(
                "wallet.topup",
                user_id=current_user.id,
                metadata={"lei": lei_amount, "spots": added, "receipt": token},
                commit=True,
            )
            promo_code = request.form.get("promo_code", "").strip()
            if promo_code:
                try:
                    bonus, pcode = promo_service.apply_topup_promo(current_user, added, promo_code)
                    flash(f"Promo {pcode}: +{bonus} bonus {config.WALLET_CURRENCY_NAME.lower()}.", "success")
                except ValueError as exc:
                    flash(str(exc), "warning")
            n8n_events.on_wallet_event(current_user, "topup", added, f"Top-up {lei_amount} lei")
            flash(f"Added {added} {config.WALLET_CURRENCY_NAME.lower()} to your wallet (mock payment).", "success")
        except ValueError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("wallet"))

    return render_template(
        "wallet_topup.html",
        plan=plan,
        subscription_monthly_lei=config.SUBSCRIPTION_MONTHLY_LEI,
        subscription_monthly_spots=config.SUBSCRIPTION_MONTHLY_SPOTS,
    )


@app.route("/portal/my-spots", methods=["GET", "POST"])
@login_required
def my_spots():
    denied = _require_driver_portal()
    if denied:
        return denied

    if _is_demo():
        return render_template(
            "my_spots.html",
            owned=_demo_owned_spots(),
            claimable=[],
            my_bookings=[],
            default_instant_hourly=config.DEFAULT_INSTANT_PRICE_PER_HOUR,
            default_schedule_deposit=config.DEFAULT_SCHEDULE_DEPOSIT,
            default_schedule_hourly=config.DEFAULT_SCHEDULE_PRICE_PER_HOUR,
            pricing_default_min=config.PRICING_DEFAULT_MIN_TENTHS / 10,
            pricing_default_max=config.PRICING_DEFAULT_MAX_TENTHS / 10,
            is_demo=True,
        )

    plates = user_plate_values(current_user)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "claim":
            device_id = request.form.get("device_id", type=int)
            device = Device.query.get_or_404(device_id)
            if device.owner_user_id:
                flash("This spot is already owned.", "warning")
            elif normalize_plate(device.assigned_plate or "") not in plates:
                flash("You can only claim spots assigned to your verified plates.", "danger")
            else:
                device.owner_user_id = current_user.id
                db.session.commit()
                activity_log.log_activity(
                    "spot.claimed",
                    user_id=current_user.id,
                    device_id=device.id,
                    metadata={"spot_label": device.spot_label},
                    commit=True,
                )
                flash(f"You now own spot {device.spot_label}.", "success")

        elif action == "save_listing":
            device_id = request.form.get("device_id", type=int)
            device = Device.query.filter_by(id=device_id, owner_user_id=current_user.id).first()
            if not device:
                flash("Spot not found.", "danger")
            else:
                listing = SpotListing.query.filter_by(device_id=device.id).first()
                if not listing:
                    listing = SpotListing(owner_id=current_user.id, device_id=device.id)
                    db.session.add(listing)
                listing.is_active = request.form.get("is_active") == "1"
                listing.approval_mode = request.form.get("approval_mode", "auto")
                listing.pricing_mode = request.form.get("pricing_mode", "manual")
                listing.owner_min_tenths = spot_prices.parse_decimal_to_tenths(
                    request.form.get("owner_min_price"),
                    config.PRICING_DEFAULT_MIN_TENTHS,
                )
                listing.owner_max_tenths = spot_prices.parse_decimal_to_tenths(
                    request.form.get("owner_max_price"),
                    config.PRICING_DEFAULT_MAX_TENTHS,
                )
                if listing.owner_min_tenths > listing.owner_max_tenths:
                    listing.owner_max_tenths = listing.owner_min_tenths

                instant_tenths = spot_prices.parse_decimal_to_tenths(
                    request.form.get("instant_price"),
                    (listing.instant_price_per_hour or 10) * 10,
                )
                schedule_tenths = spot_prices.parse_decimal_to_tenths(
                    request.form.get("schedule_price"),
                    (listing.schedule_price_per_hour or 8) * 10,
                )
                deposit_tenths = spot_prices.parse_decimal_to_tenths(
                    request.form.get("schedule_deposit"),
                    (listing.schedule_deposit_spots or 5) * 10,
                )
                listing.instant_price_tenths = max(listing.owner_min_tenths, min(listing.owner_max_tenths, instant_tenths))
                listing.schedule_price_tenths = max(listing.owner_min_tenths, min(listing.owner_max_tenths, schedule_tenths))
                listing.schedule_deposit_tenths = deposit_tenths
                listing.instant_price_per_hour = (listing.instant_price_tenths + 99) // 100
                listing.schedule_price_per_hour = (listing.schedule_price_tenths + 99) // 100
                listing.schedule_deposit_spots = (deposit_tenths + 99) // 100
                listing.description = (request.form.get("description") or "").strip() or None
                listing.updated_at = _now()
                db.session.commit()
                activity_log.log_activity(
                    "listing.updated",
                    user_id=current_user.id,
                    listing_id=listing.id,
                    device_id=device.id,
                    metadata={"pricing_mode": listing.pricing_mode, "is_active": listing.is_active},
                    commit=True,
                )
                if listing.pricing_mode in ("auto", "suggest"):
                    pricing_engine.refresh_listing_prices(listing)
                flash("Listing saved.", "success")

        elif action == "refresh_pricing":
            listing = SpotListing.query.filter_by(
                id=request.form.get("listing_id", type=int),
                owner_id=current_user.id,
            ).first_or_404()
            result = pricing_engine.refresh_listing_prices(listing)
            activity_log.log_activity(
                "pricing.refreshed",
                user_id=current_user.id,
                listing_id=listing.id,
                device_id=listing.device_id,
                metadata=result,
                commit=True,
            )
            flash(f"Prices updated: {result.get('instant')} {config.WALLET_CURRENCY_NAME.lower()}/h instant.", "success")

        elif action == "accept_suggestion":
            listing = SpotListing.query.filter_by(
                id=request.form.get("listing_id", type=int),
                owner_id=current_user.id,
            ).first_or_404()
            try:
                pricing_engine.accept_suggestion(listing)
                activity_log.log_activity(
                    "pricing.suggestion_accepted",
                    user_id=current_user.id,
                    listing_id=listing.id,
                    commit=True,
                )
                flash("Suggested prices applied to your listing.", "success")
            except ValueError as exc:
                flash(str(exc), "danger")

        elif action == "approve_booking":
            booking = SpotBooking.query.get_or_404(request.form.get("booking_id", type=int))
            try:
                spots_service.owner_approve_booking(booking, current_user)
                activity_log.log_activity(
                    "booking.approved",
                    user_id=current_user.id,
                    listing_id=booking.listing_id,
                    booking_id=booking.id,
                    commit=True,
                )
                n8n_events.on_booking_event(booking, booking.status)
                flash("Booking approved. The renter can park during the reserved window.", "success")
            except ValueError as exc:
                flash(str(exc), "danger")

        elif action == "reject_booking":
            booking = SpotBooking.query.get_or_404(request.form.get("booking_id", type=int))
            try:
                spots_service.owner_reject_booking(booking, current_user)
                activity_log.log_activity(
                    "booking.rejected",
                    user_id=current_user.id,
                    listing_id=booking.listing_id,
                    booking_id=booking.id,
                    commit=True,
                )
                n8n_events.on_booking_event(booking, "rejected")
                flash("Booking rejected and deposit refunded if applicable.", "info")
            except ValueError as exc:
                flash(str(exc), "danger")

        return redirect(url_for("my_spots"))

    owned_devices = Device.query.filter_by(owner_user_id=current_user.id).all()
    owned = []
    for device in owned_devices:
        listing = SpotListing.query.filter_by(device_id=device.id).first()
        pending = []
        if listing:
            pending = (
                SpotBooking.query.filter_by(listing_id=listing.id, status="pending_approval")
                .order_by(SpotBooking.starts_at.asc())
                .all()
            )
        if listing and listing.pricing_mode in ("auto", "suggest"):
            pricing_engine.refresh_listing_prices(listing, commit=False)
        owned.append({
            "device": device,
            "listing": listing,
            "pending": pending,
            "instant_display": spot_prices.format_tenths(
                spot_prices.effective_instant_tenths(listing) if listing else None
            ),
            "schedule_display": spot_prices.format_tenths(
                spot_prices.effective_schedule_tenths(listing) if listing else None
            ),
        })
    db.session.commit()

    claimable = []
    if plates:
        candidates = Device.query.filter(Device.owner_user_id.is_(None)).order_by(Device.spot_label.asc()).all()
        claimable = [
            d for d in candidates
            if normalize_plate(d.assigned_plate or "") in plates
        ]

    listing_ids = [item["listing"].id for item in owned if item["listing"]]
    my_bookings = []
    if listing_ids:
        my_bookings = (
            SpotBooking.query.filter(SpotBooking.listing_id.in_(listing_ids))
            .order_by(SpotBooking.created_at.desc())
            .limit(20)
            .all()
        )

    return render_template(
        "my_spots.html",
        owned=owned,
        claimable=claimable,
        my_bookings=my_bookings,
        default_instant_hourly=config.DEFAULT_INSTANT_PRICE_PER_HOUR,
        default_schedule_deposit=config.DEFAULT_SCHEDULE_DEPOSIT,
        default_schedule_hourly=config.DEFAULT_SCHEDULE_PRICE_PER_HOUR,
        pricing_default_min=config.PRICING_DEFAULT_MIN_TENTHS / 10,
        pricing_default_max=config.PRICING_DEFAULT_MAX_TENTHS / 10,
        is_demo=False,
    )


@app.route("/portal/api/geocode")
@login_required
def api_geocode():
    denied = _require_driver_portal()
    if denied:
        return jsonify({"results": []})
    q = request.args.get("q", "")
    limit = min(10, max(1, request.args.get("limit", type=int) or 8))
    return jsonify({"results": geocode_search(q, limit=limit)})


@app.route("/portal/receipt/<token>")
@login_required
def wallet_receipt(token):
    denied = _require_driver_portal()
    if denied:
        return denied
    data = receipt_pdf.load_receipt_bytes(token)
    if not data:
        abort(404)
    return Response(
        data,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="spotflow-receipt-{token[:8]}.pdf"'},
    )


@app.route("/portal/find-parking", methods=["GET", "POST"])
@login_required
def find_parking():
    denied = _require_driver_portal()
    if denied:
        return denied

    user_plates = user_plate_values(current_user)

    search = None
    if request.args.get("lat") and request.args.get("lng"):
        search = {
            "lat": request.args.get("lat", type=float),
            "lng": request.args.get("lng", type=float),
            "label": request.args.get("q") or request.args.get("label") or "Search location",
        }
    elif request.args.get("q"):
        results = geocode_search(request.args.get("q", ""), limit=1)
        if results:
            search = {
                "lat": results[0]["lat"],
                "lng": results[0]["lng"],
                "label": results[0]["label"],
            }

    if _is_demo():
        if request.method == "POST":
            return _demo_process_find_parking_post(user_plates or ["B123MAB"])
        listings = _demo_rental_listings()
        balance = _demo_wallet_balance()
        return _render_find_parking_page(
            listings,
            user_plates or ["B123MAB"],
            balance,
            _demo_renter_bookings(),
            is_demo=True,
            search=search,
        )

    spots_service.ensure_user_wallet(current_user)

    if request.method == "POST":
        if not user_plates:
            flash("Add a verified plate in account settings before booking.", "warning")
            return redirect(url_for("find_parking"))

        listing_id = request.form.get("listing_id", type=int)
        listing = SpotListing.query.filter_by(id=listing_id, is_active=True).first()
        if not listing:
            flash("Listing not found or inactive.", "danger")
            return redirect(url_for("find_parking"))

        renter_plate = normalize_plate(request.form.get("renter_plate", ""))
        if renter_plate not in user_plates:
            flash("Select one of your verified plates.", "danger")
            return redirect(url_for("find_parking"))

        action = request.form.get("action")
        try:
            if action == "instant_book":
                hours = request.form.get("hours", type=int) or config.MIN_INSTANT_HOURS
                activity_log.log_activity(
                    "booking.instant_attempt",
                    user_id=current_user.id,
                    listing_id=listing.id,
                    device_id=listing.device_id,
                    metadata={"hours": hours, "plate": renter_plate},
                    commit=True,
                )
                booking = spots_service.create_instant_booking(
                    listing, current_user, renter_plate, hours
                )
                activity_log.log_activity(
                    "booking.instant_created",
                    user_id=current_user.id,
                    listing_id=listing.id,
                    booking_id=booking.id,
                    metadata={"status": booking.status, "total_spots": booking.total_spots},
                    commit=True,
                )
                n8n_events.on_booking_event(booking, "requested")
                if booking.status != "pending_approval":
                    n8n_events.on_booking_event(booking, booking.status)
                confirm = {
                    "spot": listing.device.spot_label,
                    "plate": renter_plate,
                    "total": booking.total_spots,
                    "hours": hours,
                    "status": booking.status,
                    "type": "instant",
                }
                return redirect(
                    url_for(
                        "find_parking",
                        **_find_parking_search_redirect_args(
                            {"device": listing.device},
                            booking_confirmation=confirm,
                        ),
                    )
                )
            elif action == "schedule_book":
                starts_raw = request.form.get("starts_at", "")
                ends_raw = request.form.get("ends_at", "")
                try:
                    starts_at = datetime.fromisoformat(starts_raw)
                    ends_at = datetime.fromisoformat(ends_raw)
                except ValueError:
                    flash("Invalid date/time.", "danger")
                    return redirect(url_for("find_parking"))
                if starts_at.tzinfo is None:
                    starts_at = starts_at.replace(tzinfo=timezone.utc)
                if ends_at.tzinfo is None:
                    ends_at = ends_at.replace(tzinfo=timezone.utc)
                activity_log.log_activity(
                    "booking.schedule_attempt",
                    user_id=current_user.id,
                    listing_id=listing.id,
                    device_id=listing.device_id,
                    metadata={"starts": starts_raw, "ends": ends_raw},
                    commit=True,
                )
                booking = spots_service.create_scheduled_booking(
                    listing, current_user, renter_plate, starts_at, ends_at
                )
                activity_log.log_activity(
                    "booking.schedule_created",
                    user_id=current_user.id,
                    listing_id=listing.id,
                    booking_id=booking.id,
                    metadata={"status": booking.status, "total_spots": booking.total_spots},
                    commit=True,
                )
                n8n_events.on_booking_event(booking, "requested")
                if booking.status != "pending_approval":
                    n8n_events.on_booking_event(booking, booking.status)
                confirm = {
                    "spot": listing.device.spot_label,
                    "plate": renter_plate,
                    "total": booking.deposit_spots or booking.total_spots,
                    "hours": max(1, int((ends_at - starts_at).total_seconds() // 3600) or 1),
                    "status": booking.status,
                    "type": "scheduled",
                    "starts": starts_at.strftime("%d %b %H:%M"),
                    "ends": ends_at.strftime("%d %b %H:%M"),
                }
                return redirect(
                    url_for(
                        "find_parking",
                        **_find_parking_search_redirect_args(
                            {"device": listing.device},
                            booking_confirmation=confirm,
                        ),
                    )
                )
            else:
                flash("Unknown action.", "danger")
        except ValueError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("find_parking"))

    active_listings = (
        SpotListing.query.filter_by(is_active=True)
        .join(Device)
        .order_by(Device.spot_label.asc())
        .all()
    )
    listings = []
    for lst in active_listings:
        if lst.owner_id == current_user.id:
            continue
        if lst.pricing_mode in ("auto", "suggest"):
            pricing_engine.refresh_listing_prices(lst, commit=False)
        inst = spot_prices.effective_instant_hundredths(lst)
        sched = spot_prices.effective_schedule_hundredths(lst)
        dep = spot_prices.effective_deposit_hundredths(lst)
        listings.append({
            "listing": lst,
            "device": lst.device,
            "instant_display": spot_prices.format_hundredths(inst),
            "schedule_display": spot_prices.format_hundredths(sched),
            "deposit_display": spot_prices.format_hundredths(dep),
            "instant_hundredths": inst,
            "schedule_hundredths": sched,
            "deposit_hundredths": dep,
            "approval_mode": lst.approval_mode,
            "pricing_mode": lst.pricing_mode,
        })
        activity_log.log_activity(
            "listing.card_view",
            user_id=current_user.id,
            listing_id=lst.id,
            device_id=lst.device_id,
            commit=False,
        )
    db.session.commit()
    mapped = any(item["device"].latitude for item in listings)

    renter_bookings = (
        SpotBooking.query.filter_by(renter_id=current_user.id)
        .order_by(SpotBooking.created_at.desc())
        .limit(15)
        .all()
    )

    balance = spots_service.user_balance(current_user)
    return _render_find_parking_page(
        listings,
        user_plates,
        balance,
        renter_bookings,
        is_demo=False,
        search=search,
    )


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
        <title>Spotflow Receipt - {fine.id}</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; padding: 40px; color: #333; }}
            .header {{ font-size: 24px; font-weight: bold; margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
            .details {{ margin-bottom: 30px; line-height: 1.6; }}
            .stamp {{ display: inline-block; padding: 10px 20px; border: 3px solid #4CAF50; color: #4CAF50; font-weight: bold; font-size: 20px; border-radius: 8px; transform: rotate(-5deg); margin-top: 20px; }}
            @media print {{ body {{ padding: 0; }} }}
        </style>
    </head>
    <body onload="window.print()">
        <div class="header">Spotflow - Official Resolution Receipt</div>
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
