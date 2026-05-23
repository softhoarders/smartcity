"""HTTP API for n8n workflows (cron jobs, wait loops, admin automation)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from sqlalchemy import func

import config
import pricing_engine
import spots_service
from activity_log import count_events
from models import Device, Fine, SpotBooking, SpotListing, User, UserPlate, db
from security import require_n8n_api_key

n8n_bp = Blueprint("n8n_api", __name__, url_prefix="/api/n8n")


def _utcnow():
    return datetime.now(timezone.utc)


@n8n_bp.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "n8n_enabled": config.N8N_ENABLED,
        "api_configured": bool(config.N8N_API_KEY),
    })


@n8n_bp.route("/fines/<int:fine_id>", methods=["GET"])
@require_n8n_api_key
def get_fine(fine_id):
    fine = Fine.query.get_or_404(fine_id)
    from n8n_events import fine_payload

    return jsonify(fine_payload(fine, fine.device))


@n8n_bp.route("/fines", methods=["GET"])
@require_n8n_api_key
def list_fines():
    since_hours = request.args.get("since_hours", type=int) or 168
    since = _utcnow() - timedelta(hours=since_hours)
    q = Fine.query.filter(Fine.created_at >= since).order_by(Fine.created_at.desc())
    if request.args.get("unresolved") == "1":
        q = q.filter_by(resolved=False)
    from n8n_events import fine_payload

    return jsonify([fine_payload(f, f.device) for f in q.limit(200).all()])


@n8n_bp.route("/bookings/<int:booking_id>", methods=["GET"])
@require_n8n_api_key
def get_booking(booking_id):
    booking = SpotBooking.query.get_or_404(booking_id)
    from n8n_events import booking_payload

    return jsonify(booking_payload(booking))


@n8n_bp.route("/bookings/<int:booking_id>/approve", methods=["POST"])
@require_n8n_api_key
def approve_booking(booking_id):
    booking = SpotBooking.query.get_or_404(booking_id)
    if booking.status != "pending_approval":
        return jsonify({"error": "not_pending", "status": booking.status}), 400
    owner = booking.listing.owner
    spots_service.owner_approve_booking(booking, owner)
    from n8n_events import on_booking_event

    on_booking_event(booking, booking.status)
    return jsonify({"ok": True, "status": booking.status})


@n8n_bp.route("/activity/summary", methods=["GET"])
@require_n8n_api_key
def activity_summary():
    hours = request.args.get("hours", type=int) or 24
    since = _utcnow() - timedelta(hours=hours)
    return jsonify({
        "hours": hours,
        "listing_views": count_events(
            ["listing.card_view", "page.view.find_parking"],
            since=since,
        ),
        "booking_attempts": count_events(
            ["booking.instant_attempt", "booking.schedule_attempt"],
            since=since,
        ),
        "bookings_created": count_events(
            ["booking.instant_created", "booking.schedule_created"],
            since=since,
        ),
    })


@n8n_bp.route("/pricing/refresh-all", methods=["POST"])
@require_n8n_api_key
def pricing_refresh_all():
    updated = pricing_engine.refresh_all_active_listings()
    return jsonify({"ok": True, "listings_updated": updated})


@n8n_bp.route("/pricing/signals/<int:listing_id>", methods=["GET"])
@require_n8n_api_key
def pricing_signals(listing_id):
    listing = SpotListing.query.get_or_404(listing_id)
    device = listing.device
    signals = pricing_engine.collect_demand_signals(listing, device)
    return jsonify(signals)


@n8n_bp.route("/subscriptions/process-renewals", methods=["POST"])
@require_n8n_api_key
def subscriptions_renew():
    before = User.query.filter_by(subscription_active=True).count()
    spots_service.process_subscription_renewals()
    return jsonify({"ok": True, "active_subscribers": before})


@n8n_bp.route("/subscribers", methods=["GET"])
@require_n8n_api_key
def list_subscribers():
    users = User.query.filter_by(subscription_active=True).all()
    return jsonify([
        {
            "user_id": u.id,
            "email": u.email,
            "name": u.name,
            "balance": int(u.spots_balance or 0),
            "next_billing": u.subscription_next_billing_at.isoformat() if u.subscription_next_billing_at else None,
        }
        for u in users
    ])


@n8n_bp.route("/report/weekly", methods=["GET"])
@require_n8n_api_key
def weekly_report():
    since = _utcnow() - timedelta(days=7)
    fines = Fine.query.filter(Fine.created_at >= since).all()
    resolved = sum(1 for f in fines if f.resolved)
    active_bookings = SpotBooking.query.filter(
        SpotBooking.created_at >= since,
        SpotBooking.status.notin_(("rejected",)),
    ).count()
    rental_income = (
        db.session.query(func.coalesce(func.sum(SpotBooking.paid_spots), 0))
        .filter(SpotBooking.created_at >= since)
        .scalar()
    )
    devices_online = Device.query.filter(Device.last_seen >= since).count()
    return jsonify({
        "period_days": 7,
        "violations_total": len(fines),
        "violations_resolved": resolved,
        "bookings": active_bookings,
        "spots_transferred": int(rental_income or 0),
        "devices_seen": devices_online,
        "pending_plates": UserPlate.query.filter_by(verification_status="pending").count(),
    })


@n8n_bp.route("/devices/<int:device_id>/authorized-plate", methods=["GET"])
@require_n8n_api_key
def device_authorized_plate(device_id):
    device = Device.query.get_or_404(device_id)
    spots_service.refresh_booking_statuses()
    plate = spots_service.effective_assigned_plate(device)
    return jsonify({
        "device_id": device.id,
        "spot_label": device.spot_label,
        "authorized_plate": plate,
        "assigned_plate": device.assigned_plate,
    })
