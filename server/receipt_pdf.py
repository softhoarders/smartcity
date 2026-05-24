"""PDF receipt generation for wallet and booking events."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from io import BytesIO

from fpdf import FPDF

import config

RECEIPT_DIR = os.path.join(config.DATA_DIR, "receipts")
try:
    os.makedirs(RECEIPT_DIR, exist_ok=True)
except OSError:
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_receipt_token() -> str:
    return secrets.token_urlsafe(24)


def receipt_path(token: str) -> str:
    safe = "".join(c for c in token if c.isalnum() or c in "-_")
    return os.path.join(RECEIPT_DIR, f"{safe}.pdf")


def _build_pdf(title: str, lines: list[tuple[str, str]]) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Spotflow", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, title, ln=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Issued: {_utcnow().strftime('%d %b %Y %H:%M UTC')}", ln=True)
    pdf.ln(6)
    for label, value in lines:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(50, 7, f"{label}:", ln=False)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 7, str(value))
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(
        0,
        5,
        f"1 {config.WALLET_CURRENCY_SINGULAR} = 1 lei (RON). This is a platform receipt, not a tax invoice.",
    )
    out = BytesIO()
    pdf.output(out)
    return out.getvalue()


def save_receipt(token: str, title: str, lines: list[tuple[str, str]]) -> str:
    path = receipt_path(token)
    data = _build_pdf(title, lines)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def load_receipt_bytes(token: str) -> bytes | None:
    path = receipt_path(token)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()
