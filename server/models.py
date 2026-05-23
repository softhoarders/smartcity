from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class Device(db.Model):
    """A registered Raspberry Pi parking monitor."""
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    mac_address = db.Column(db.String(17), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), default="Unnamed Device")
    assigned_plate = db.Column(db.String(20), nullable=True)
    spot_label = db.Column(db.String(50), default="Unassigned Spot")
    last_seen = db.Column(db.DateTime, nullable=True)
    last_wifi = db.Column(db.Integer, nullable=True)
    last_temp = db.Column(db.Float, nullable=True)
    capture_requested = db.Column(db.Boolean, default=False)
    current_status = db.Column(db.String(20), default="empty")
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    fines = db.relationship("Fine", backref="device", lazy="dynamic",
                            order_by="Fine.created_at.desc()")

    @property
    def is_online(self):
        if self.last_seen is None:
            return False
        from config import OFFLINE_THRESHOLD_SECONDS
        now = datetime.now(timezone.utc)
        delta = (now - self.last_seen.replace(tzinfo=timezone.utc)).total_seconds()
        return delta < OFFLINE_THRESHOLD_SECONDS

    def to_dict(self):
        return {
            "id": self.id,
            "mac_address": self.mac_address,
            "name": self.name,
            "assigned_plate": self.assigned_plate,
            "spot_label": self.spot_label,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "last_wifi": self.last_wifi,
            "last_temp": self.last_temp,
            "capture_requested": self.capture_requested,
            "current_status": self.current_status,
            "is_online": self.is_online,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Fine(db.Model):
    """A logged parking violation."""
    __tablename__ = "fines"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=False)
    detected_plate = db.Column(db.String(20), nullable=False)
    expected_plate = db.Column(db.String(20), nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)
    first_seen = db.Column(db.DateTime, nullable=False)
    last_seen = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, default=0)
    confidence_score = db.Column(db.Float, nullable=True)
    resolved = db.Column(db.Boolean, default=False)
    photo_requested = db.Column(db.Boolean, default=False)
    photo_sent_at = db.Column(db.DateTime, nullable=True)
    appeal_status = db.Column(db.String(20), default="none")
    appeal_reason = db.Column(db.String(500), nullable=True)
    last_notified = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "device_name": self.device.name if self.device else "Unknown",
            "spot_label": self.device.spot_label if self.device else "Unknown",
            "detected_plate": self.detected_plate,
            "expected_plate": self.expected_plate,
            "image_filename": self.image_filename,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "duration_minutes": self.duration_minutes,
            "confidence_score": self.confidence_score,
            "resolved": self.resolved,
            "photo_requested": self.photo_requested,
            "photo_sent_at": self.photo_sent_at.isoformat() if self.photo_sent_at else None,
            "appeal_status": self.appeal_status,
            "appeal_reason": self.appeal_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class UserPlate(db.Model):
    """License plates registered to a driver account."""
    __tablename__ = "user_plates"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    plate = db.Column(db.String(20), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("plates", lazy="dynamic", cascade="all, delete-orphan"))


class User(UserMixin, db.Model):
    """A driver user account."""
    __tablename__ = "users"
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(128), nullable=False)
    license_plate = db.Column(db.String(20), nullable=False, default="")
    name = db.Column(db.String(100), default="Driver")
    role = db.Column(db.String(20), default="driver", nullable=False)
    verification_status = db.Column(db.String(20), default="approved", nullable=False)
    verification_document = db.Column(db.String(255), nullable=True)
    verification_notes = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # We use UserMixin which provides is_authenticated, is_active, is_anonymous, get_id()

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_verified_driver(self):
        return self.role == "driver"

    def plate_values(self):
        """Normalized plates for this account (UserPlate rows + legacy column)."""
        values = [row.plate for row in self.plates]
        legacy = (self.license_plate or "").strip().upper()
        legacy = "".join(ch for ch in legacy if ch.isalnum())
        if legacy and legacy not in values:
            values.append(legacy)
        return values

class FineMessage(db.Model):
    """Stores chat history for fine appeals."""
    __tablename__ = "fine_messages"
    
    id = db.Column(db.Integer, primary_key=True)
    fine_id = db.Column(db.Integer, db.ForeignKey('fines.id'), nullable=False)
    sender = db.Column(db.String(50), nullable=False) # 'User', 'Admin', 'AI'
    content = db.Column(db.Text, nullable=False)
    attachment_filename = db.Column(db.String(255), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    fine = db.relationship('Fine', backref=db.backref('messages', lazy="dynamic", order_by="FineMessage.timestamp.asc()"))

class PushSubscription(db.Model):
    """Stores Web Push subscriptions for users."""
    __tablename__ = "push_subscriptions"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subscription_info = db.Column(db.Text, nullable=False)  # JSON string of subscription object
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    user = db.relationship('User', backref=db.backref('push_subscriptions', lazy=True))
