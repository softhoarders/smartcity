"""
camera.py — USB camera capture module.

Captures a single 720p frame from a USB webcam, saves to disk, and
immediately releases the camera to save resources.
"""

import os
import time
import cv2
import config


def capture_image() -> str | None:
    """
    Capture a single 720p image from the USB camera.

    If PARKWATCH_TEST_IMAGE is set, copies that file instead
    (useful for development on machines without a camera).

    Returns:
        Path to saved image file, or None on failure.
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"capture_{timestamp}.jpg"
    filepath = os.path.join(config.CAPTURE_DIR, filename)

    # --- Test mode: use a static image ---
    if config.TEST_IMAGE and os.path.exists(config.TEST_IMAGE):
        import shutil
        shutil.copy2(config.TEST_IMAGE, filepath)
        print(f"[CAM] Test mode — copied {config.TEST_IMAGE} → {filepath}")
        return filepath

    # --- Real camera capture ---
    try:
        cap = cv2.VideoCapture(config.CAMERA_INDEX)
        if not cap.isOpened():
            print("[CAM] ERROR: Could not open camera.")
            return None

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAPTURE_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAPTURE_HEIGHT)

        # Let the camera auto-adjust (a few warm-up frames)
        for _ in range(5):
            cap.read()
            time.sleep(0.1)

        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            print("[CAM] ERROR: Failed to capture frame.")
            return None

        cv2.imwrite(filepath, frame)
        print(f"[CAM] Captured {frame.shape[1]}x{frame.shape[0]} → {filepath}")
        return filepath

    except Exception as e:
        print(f"[CAM] ERROR: {e}")
        return None


def cleanup_old_captures(max_files: int = 50):
    """Remove old capture files, keeping only the most recent `max_files`."""
    try:
        files = sorted(
            [os.path.join(config.CAPTURE_DIR, f) for f in os.listdir(config.CAPTURE_DIR)
             if f.endswith(".jpg")],
            key=os.path.getmtime,
        )
        if len(files) > max_files:
            for f in files[:-max_files]:
                os.remove(f)
                print(f"[CAM] Cleaned up old capture: {f}")
    except Exception as e:
        print(f"[CAM] Cleanup error: {e}")
