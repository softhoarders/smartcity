"""
plate_reader.py — License plate detection & OCR (energy-aware, improved accuracy).

Pipeline: preprocess → region candidates → multi-threshold OCR → pattern scoring.
Uses Tesseract with confidence scores and several PSM modes per crop.
"""

from __future__ import annotations

import re

import cv2
import imutils
import numpy as np
import pytesseract

import config

_TESS_CFG_BASE = (
    "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
)
_PSM_MODES = (7, 8, 13)


def read_plate(image_path: str) -> tuple[str, float] | tuple[None, None]:
    print(f"[PLATE] Processing: {image_path}")

    img = cv2.imread(image_path)
    if img is None:
        print("[PLATE] ERROR: Could not load image.")
        return None, None

    img = imutils.resize(img, width=config.PROCESSING_MAX_WIDTH)
    h, w = img.shape[:2]
    gray = _preprocess_gray(img)

    candidates = _find_candidates(gray, w, h)
    if not candidates:
        print("[PLATE] No plate candidates found.")
        return _full_frame_fallback(gray)

    best_plate = None
    best_score = 0.0

    for x, y, cw, ch in candidates[:12]:
        pad = max(4, int(min(cw, ch) * 0.08))
        y1, y2 = max(0, y - pad), min(h, y + ch + pad)
        x1, x2 = max(0, x - pad), min(w, x + cw + pad)
        crop = gray[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        for plate_text, ocr_score in _ocr_variants(crop):
            cleaned = _normalize_plate(plate_text)
            if not cleaned:
                continue
            total = _plate_confidence(cleaned) + ocr_score
            print(f"[PLATE] Candidate: '{plate_text}' → '{cleaned}' (score: {total:.1f})")
            if total > best_score:
                best_score = total
                best_plate = cleaned

    if best_plate:
        confidence = min(99.0, round(55.0 + best_score * 4.5, 1))
        print(f"[PLATE] Detected: {best_plate} (confidence: {confidence})")
        return best_plate, confidence

    return _full_frame_fallback(gray)


def _preprocess_gray(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    return gray


def _find_candidates(gray: np.ndarray, w: int, h: int) -> list[tuple[int, int, int, int]]:
    candidates: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int, int, int]] = set()

    def add(x: int, y: int, cw: int, ch: int) -> None:
        aspect = cw / ch if ch > 0 else 0
        area_ratio = (cw * ch) / (w * h) if (w * h) > 0 else 0
        if not (1.4 < aspect < 7.5 and cw > 50 and ch > 12):
            return
        if not (0.002 < area_ratio < 0.2):
            return
        key = (x // 8, y // 8, cw // 8, ch // 8)
        if key in seen:
            return
        seen.add(key)
        candidates.append((x, y, cw, ch))

    edges = cv2.Canny(gray, 40, 180)
    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:40]:
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) == 4:
            x, y, cw, ch = cv2.boundingRect(approx)
            add(x, y, cw, ch)

    for x, y, cw, ch, *_ in _morph_detect(gray, w, h):
        add(x, y, cw, ch)

    candidates.sort(key=lambda b: b[2] * b[3], reverse=True)
    return candidates


def _ocr_variants(crop: np.ndarray) -> list[tuple[str, float]]:
    results: list[tuple[str, float]] = []
    scale = 2 if max(crop.shape[:2]) < 120 else 1
    if scale > 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    variants = [
        crop,
        cv2.adaptiveThreshold(crop, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5),
    ]
    _, otsu = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(otsu)

    for variant in variants:
        for psm in _PSM_MODES:
            text, conf = _tesseract_read(variant, psm)
            if text:
                results.append((text, conf))
    return results


def _tesseract_read(img: np.ndarray, psm: int) -> tuple[str, float]:
    cfg = f"--psm {psm} --oem 3 {_TESS_CFG_BASE}"
    try:
        data = pytesseract.image_to_data(
            img, lang=config.TESSERACT_LANG, config=cfg, output_type=pytesseract.Output.DICT
        )
    except Exception as e:
        print(f"[PLATE] OCR error (psm {psm}): {e}")
        return "", 0.0

    tokens = []
    confidences = []
    for word, conf in zip(data.get("text", []), data.get("conf", [])):
        if not word or not str(word).strip():
            continue
        try:
            c = float(conf)
        except (TypeError, ValueError):
            continue
        if c < 0:
            continue
        tokens.append(str(word).strip())
        confidences.append(c)

    if not tokens:
        return "", 0.0

    text = "".join(tokens)
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return text, mean_conf / 10.0


def _full_frame_fallback(gray: np.ndarray) -> tuple[str, float] | tuple[None, None]:
    """Last resort: OCR a wide band in the lower half where plates often appear."""
    h, w = gray.shape[:2]
    band = gray[int(h * 0.45) : h, :]
    band = imutils.resize(band, width=min(900, w))
    text, conf = _tesseract_read(band, 6)
    cleaned = _normalize_plate(text)
    if cleaned:
        confidence = min(88.0, round(45.0 + conf * 3.0 + _plate_confidence(cleaned) * 2, 1))
        print(f"[PLATE] Fallback band OCR: {cleaned} ({confidence})")
        return cleaned, confidence
    print("[PLATE] No valid plate text found.")
    return None, None


def _morph_detect(gray, w, h):
    candidates = []
    rect_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, rect_kernel)
    _, thresh = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 7))
    dilated = cv2.dilate(thresh, dilate_kernel, iterations=2)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        aspect = cw / ch if ch > 0 else 0
        area_ratio = (cw * ch) / (w * h) if (w * h) > 0 else 0
        if 1.5 < aspect < 7.0 and 0.005 < area_ratio < 0.15 and cw > 60:
            candidates.append((x, y, cw, ch, None))
    return candidates


def _normalize_plate(text: str) -> str | None:
    if not text:
        return None

    cleaned = re.sub(r"[^A-Za-z0-9]", "", text.upper())
    if len(cleaned) < 4 or len(cleaned) > 12:
        return None

    cleaned = cleaned.replace("O", "0").replace("I", "1").replace("S", "5")

    ro_match = re.match(r"^([A-Z0-9]{1,2})(\d{2,3})([A-Z0-9]{3})$", cleaned)
    if ro_match:
        county = ro_match.group(1).replace("0", "O").replace("1", "I").replace("5", "S")
        digits = ro_match.group(2)
        suffix = ro_match.group(3).replace("0", "O").replace("1", "I").replace("5", "S")
        return f"{county} {digits} {suffix}"

    b_match = re.match(r"^(B)(\d{3})([A-Z0-9]{3})$", cleaned)
    if b_match:
        suffix = b_match.group(3).replace("0", "O").replace("1", "I").replace("5", "S")
        return f"B {b_match.group(2)} {suffix}"

    if len(cleaned) >= 5:
        return cleaned
    return None


def _plate_confidence(plate: str) -> float:
    score = 0.0
    has_letters = bool(re.search(r"[A-Z]", plate))
    has_digits = bool(re.search(r"\d", plate))
    if has_letters and has_digits:
        score += 3.0

    stripped = plate.replace(" ", "")
    if re.match(r"^[A-Z]{1,2}\d{2,3}[A-Z]{3}$", stripped):
        score += 5.0
    if 6 <= len(stripped) <= 9:
        score += 2.0
    if len(stripped) < 5:
        score -= 2.0
    return score
