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
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    owner = db.relationship("User", foreign_keys=[owner_user_id], backref="owned_devices")
    listing = db.relationship(
        "SpotListing",
        backref="device",
        uselist=False,
        cascade="all, delete-orphan",
    )

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
            "owner_user_id": self.owner_user_id,
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
    verification_status = db.Column(db.String(20), default="pending", nullable=False)
    verification_document = db.Column(db.String(255), nullable=True)
    verification_notes = db.Column(db.String(500), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("plates", lazy="dynamic", cascade="all, delete-orphan"))

    @property
    def is_approved(self):
        return self.verification_status == "approved"


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
    spots_balance = db.Column(db.Integer, default=0, nullable=False)
    subscription_active = db.Column(db.Boolean, default=False, nullable=False)
    subscription_started_at = db.Column(db.DateTime, nullable=True)
    subscription_next_billing_at = db.Column(db.DateTime, nullable=True)
    twofa_enabled = db.Column(db.Boolean, default=False, nullable=False)
    twofa_secret = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # We use UserMixin which provides is_authenticated, is_active, is_anonymous, get_id()

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_verified_driver(self):
        return self.role == "driver"

    def plate_values(self, approved_only=True):
        """Normalized plates for this account (approved UserPlate rows + legacy column)."""
        rows = self.plates
        if approved_only:
            rows = rows.filter_by(verification_status="approved")
        values = [row.plate for row in rows]
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


class SpotListing(db.Model):
    """A parking spot offered for rent by its owner."""
    __tablename__ = "spot_listings"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    approval_mode = db.Column(db.String(20), default="auto", nullable=False)  # auto | manual
    instant_price_per_hour = db.Column(db.Integer, default=10, nullable=False)
    schedule_deposit_spots = db.Column(db.Integer, default=5, nullable=False)
    schedule_price_per_hour = db.Column(db.Integer, default=8, nullable=False)
    instant_price_tenths = db.Column(db.Integer, nullable=True)
    schedule_price_tenths = db.Column(db.Integer, nullable=True)
    schedule_deposit_tenths = db.Column(db.Integer, nullable=True)
    pricing_mode = db.Column(db.String(20), default="manual", nullable=False)  # manual | auto | suggest
    owner_min_tenths = db.Column(db.Integer, default=50, nullable=False)
    owner_max_tenths = db.Column(db.Integer, default=300, nullable=False)
    suggested_instant_tenths = db.Column(db.Integer, nullable=True)
    suggested_schedule_tenths = db.Column(db.Integer, nullable=True)
    dynamic_instant_tenths = db.Column(db.Integer, nullable=True)
    dynamic_schedule_tenths = db.Column(db.Integer, nullable=True)
    location_zone = db.Column(db.String(30), nullable=True)
    pricing_reason = db.Column(db.String(500), nullable=True)
    last_priced_at = db.Column(db.DateTime, nullable=True)
    description = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    owner = db.relationship("User", backref=db.backref("spot_listings", lazy="dynamic"))
    bookings = db.relationship("SpotBooking", backref="listing", lazy="dynamic")


class SpotActivityLog(db.Model):
    """Automatic log of user and system actions for demand analytics."""
    __tablename__ = "spot_activity_log"

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(60), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("spot_listings.id"), nullable=True, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=True, index=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("spot_bookings.id"), nullable=True)
    endpoint = db.Column(db.String(80), nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user = db.relationship("User", backref=db.backref("activity_logs", lazy="dynamic"))
    listing = db.relationship("SpotListing", backref=db.backref("activity_logs", lazy="dynamic"))


class SpotGeoCache(db.Model):
    """Cached Nominatim / weather data per device."""
    __tablename__ = "spot_geo_cache"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=False, unique=True)
    data_json = db.Column(db.Text, nullable=True)
    fetched_at = db.Column(db.DateTime, nullable=True)

    device = db.relationship("Device", backref=db.backref("geo_cache", uselist=False))


class SpotBooking(db.Model):
    """Instant rental or scheduled reservation for a listed spot."""
    __tablename__ = "spot_bookings"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("spot_listings.id"), nullable=False, index=True)
    renter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    renter_plate = db.Column(db.String(20), nullable=False)
    booking_type = db.Column(db.String(20), nullable=False)  # instant | scheduled
    status = db.Column(db.String(30), default="pending_approval", nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)
    deposit_spots = db.Column(db.Integer, default=0, nullable=False)
    total_spots = db.Column(db.Integer, default=0, nullable=False)
    paid_spots = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    renter = db.relationship("User", backref=db.backref("spot_bookings", lazy="dynamic"))


class SpotTransaction(db.Model):
    """Ledger entry for Spots credits and debits."""
    __tablename__ = "spot_transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(40), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    reference_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("spot_transactions", lazy="dynamic"))
