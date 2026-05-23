"""
camera.py — USB camera capture (720p, minimal warm-up, immediate release).
"""

import os
import time

import cv2

import config


def capture_image() -> str | None:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"capture_{timestamp}.jpg"
    filepath = os.path.join(config.CAPTURE_DIR, filename)

    if config.TEST_IMAGE and os.path.exists(config.TEST_IMAGE):
        import shutil

        shutil.copy2(config.TEST_IMAGE, filepath)
        print(f"[CAM] Test mode — copied {config.TEST_IMAGE} → {filepath}")
        return filepath

    cap = None
    try:
        cap = cv2.VideoCapture(config.CAMERA_INDEX, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap = cv2.VideoCapture(config.CAMERA_INDEX)
        if not cap.isOpened():
            print("[CAM] ERROR: Could not open camera.")
            return None

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAPTURE_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAPTURE_HEIGHT)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        for _ in range(config.CAMERA_WARMUP_FRAMES):
            cap.read()
            time.sleep(0.05)

        ret, frame = cap.read()
        if not ret or frame is None:
            print("[CAM] ERROR: Failed to capture frame.")
            return None

        cv2.imwrite(
            filepath,
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 85],
        )
        print(f"[CAM] Captured {frame.shape[1]}x{frame.shape[0]} → {filepath}")
        return filepath

    except Exception as e:
        print(f"[CAM] ERROR: {e}")
        return None
    finally:
        if cap is not None:
            cap.release()


def cleanup_old_captures(max_files: int = 20):
    try:
        files = sorted(
            [
                os.path.join(config.CAPTURE_DIR, f)
                for f in os.listdir(config.CAPTURE_DIR)
                if f.endswith(".jpg")
            ],
            key=os.path.getmtime,
        )
        if len(files) > max_files:
            for f in files[:-max_files]:
                os.remove(f)
                print(f"[CAM] Cleaned up old capture: {f}")
    except Exception as e:
        print(f"[CAM] Cleanup error: {e}")
