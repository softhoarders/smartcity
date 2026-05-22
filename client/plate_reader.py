"""
plate_reader.py — License plate detection & OCR.

Uses OpenCV for plate region detection (contour-based) and
Tesseract OCR for text extraction. Optimized for Raspberry Pi Zero 2.

Handles Romanian EU-format plates (e.g., B 123 ABC, CJ 01 XYZ)
and common international formats.
"""

import re
import cv2
import numpy as np
import pytesseract
import imutils
import config


def read_plate(image_path: str) -> tuple[str, float] | tuple[None, None]:
    """
    Detect and read a license plate from an image file.

    Pipeline:
        1. Load & resize image (save memory)
        2. Grayscale + bilateral filter
        3. Canny edge detection
        4. Find rectangular contours (plate candidates)
        5. Crop, threshold, OCR each candidate
        6. Post-process text and return best match

    Args:
        image_path: Path to the image file.

    Returns:
        Tuple of (Detected plate text, confidence score), or (None, None) if nothing found.
    """
    print(f"[PLATE] Processing: {image_path}")

    # 1. Load image
    img = cv2.imread(image_path)
    if img is None:
        print("[PLATE] ERROR: Could not load image.")
        return None, None

    # Resize to save memory (keep aspect ratio)
    img = imutils.resize(img, width=config.PROCESSING_MAX_WIDTH)
    original = img.copy()
    h, w = img.shape[:2]

    # 2. Grayscale + noise reduction
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)

    # 3. Edge detection
    edges = cv2.Canny(gray, 30, 200)

    # 4. Find contours — sort by area descending
    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:30]

    plate_candidates = []

    for contour in contours:
        # Approximate contour to polygon
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.018 * peri, True)

        # License plates are roughly rectangular (4 corners)
        if len(approx) == 4:
            x, y, cw, ch = cv2.boundingRect(approx)

            # Filter by aspect ratio (plates are wider than tall)
            aspect = cw / ch if ch > 0 else 0
            if 1.5 < aspect < 7.0 and cw > 60 and ch > 15:
                plate_candidates.append((x, y, cw, ch, approx))

    if not plate_candidates:
        # Fallback: try morphological approach
        plate_candidates = _morph_detect(gray, w, h)

    if not plate_candidates:
        print("[PLATE] No plate candidates found.")
        return None, None

    # 5. OCR each candidate
    best_plate = None
    best_confidence = 0

    for x, y, cw, ch, *_ in plate_candidates:
        # Crop plate region with small padding
        pad = 5
        y1 = max(0, y - pad)
        y2 = min(h, y + ch + pad)
        x1 = max(0, x - pad)
        x2 = min(w, x + cw + pad)

        plate_img = gray[y1:y2, x1:x2]

        if plate_img.size == 0:
            continue

        # Resize plate region for better OCR
        plate_img = cv2.resize(plate_img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

        # Threshold for cleaner text
        _, plate_img = cv2.threshold(plate_img, 0, 255,
                                     cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # OCR
        try:
            text = pytesseract.image_to_string(
                plate_img,
                lang=config.TESSERACT_LANG,
                config="--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            ).strip()
        except Exception as e:
            print(f"[PLATE] OCR error: {e}")
            continue

        # 6. Normalize and score
        cleaned = _normalize_plate(text)
        if cleaned:
            score = _plate_confidence(cleaned)
            print(f"[PLATE] Candidate: '{text}' → '{cleaned}' (score: {score})")
            if score > best_confidence:
                best_confidence = score
                best_plate = cleaned

    if best_plate:
        print(f"[PLATE] Detected: {best_plate} (Confidence: {best_confidence})")
    else:
        print("[PLATE] No valid plate text found.")

    return best_plate, best_confidence


def _morph_detect(gray, w, h):
    """
    Fallback plate detection using morphological operations.
    Works better on some plate types where contour detection fails.
    """
    candidates = []

    # Apply blackhat to reveal dark regions on light background
    rect_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, rect_kernel)

    # Threshold
    _, thresh = cv2.threshold(blackhat, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Dilate to merge characters
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 7))
    dilated = cv2.dilate(thresh, dilate_kernel, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        aspect = cw / ch if ch > 0 else 0
        area_ratio = (cw * ch) / (w * h) if (w * h) > 0 else 0

        if 1.5 < aspect < 7.0 and 0.005 < area_ratio < 0.15 and cw > 60:
            candidates.append((x, y, cw, ch))

    return candidates


def _normalize_plate(text: str) -> str | None:
    """
    Clean and normalize OCR output into a plate-like string.
    Removes non-alphanumeric chars, applies common OCR corrections.
    """
    if not text:
        return None

    # Remove non-alphanumeric
    cleaned = re.sub(r'[^A-Za-z0-9]', '', text.upper())

    if len(cleaned) < 4 or len(cleaned) > 12:
        return None

    # Common OCR substitutions
    cleaned = cleaned.replace('O', '0').replace('I', '1').replace('S', '5')

    # Then restore letters where they should be letters
    # Romanian plates: 1-2 letters + 2-3 digits + 3 letters
    # e.g., B123ABC, CJ01XYZ
    # Try to match Romanian format
    ro_match = re.match(r'^([A-Z0-9]{1,2})(\d{2,3})([A-Z0-9]{3})$', cleaned)
    if ro_match:
        county = ro_match.group(1)
        digits = ro_match.group(2)
        suffix = ro_match.group(3)

        # Restore letters in county code
        county = county.replace('0', 'O').replace('1', 'I').replace('5', 'S')
        # Restore letters in suffix
        suffix = suffix.replace('0', 'O').replace('1', 'I').replace('5', 'S')

        return f"{county} {digits} {suffix}"

    # Bucharest format: B + 3 digits + 3 letters
    b_match = re.match(r'^(B)(\d{3})([A-Z0-9]{3})$', cleaned)
    if b_match:
        suffix = b_match.group(3).replace('0', 'O').replace('1', 'I').replace('5', 'S')
        return f"B {b_match.group(2)} {suffix}"

    # Generic: just return cleaned with spaces
    if len(cleaned) >= 5:
        return cleaned

    return None


def _plate_confidence(plate: str) -> float:
    """
    Score a plate string by how 'plate-like' it looks.
    Higher = more likely to be a real plate.
    """
    score = 0.0

    # Has both letters and digits
    has_letters = bool(re.search(r'[A-Z]', plate))
    has_digits = bool(re.search(r'\d', plate))
    if has_letters and has_digits:
        score += 3.0

    # Romanian format match
    stripped = plate.replace(' ', '')
    if re.match(r'^[A-Z]{1,2}\d{2,3}[A-Z]{3}$', stripped):
        score += 5.0

    # Reasonable length (6-9 chars without spaces)
    if 6 <= len(stripped) <= 9:
        score += 2.0

    # Penalize very short/long
    if len(stripped) < 5:
        score -= 2.0

    return score
