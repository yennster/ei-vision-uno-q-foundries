#!/usr/bin/env python3
"""
motion-watcher.py — capture & upload frames whenever something enters
the camera's field of view.

Uses OpenCV's MOG2 background subtractor — no second model, no .eim,
no Edge Impulse inference. After a brief warmup it learns the static
scene; when foreground pixels exceed THRESHOLD (and the largest
foreground blob is bigger than MIN_AREA), the frame is handed to
capture-and-upload.sh so it lands in your EI training/testing dataset.

Architecture:

    /dev/video0 ─► MOG2 background subtraction ─► motion%, blob area
                                                        │
                          motion% ≥ THRESHOLD &         │
                          blob ≥ MIN_AREA       ────────┘
                                  │
                                  ▼
                       capture-and-upload.sh
                                  │
                                  ▼
                        EI ingestion API
                                  │
                                  ▼
                ei-data-watch-and-retrain.yml retrains

Prerequisites on the device:

    sudo apt install -y python3-opencv ffmpeg

Required env:
    EI_API_KEY        Edge Impulse API key for the target project
                      (the project receiving captured frames)

Optional env:
    THRESHOLD         % of pixels that must be foreground before a
                      capture fires.                          (default: 1.5)
    MIN_AREA          smallest contiguous blob (px²) that counts as
                      "an object." Filters out shadows/twitch. (default: 5000)
    COOLDOWN          seconds to wait after a capture before another
                                                              (default: 10)
    WARMUP            seconds of background-learning before any
                      capture is considered (gives MOG2 a stable
                      reference scene).                       (default: 5)
    CATEGORY          training | testing                      (default: training)
    LABEL             x-label sent with each upload           (default: motion)
    DEVICE            V4L2 device path                        (default: /dev/video0)
    DEVICE_INDEX      cv2 device index (overrides DEVICE)
    MAX_UPLOADS       cap per session, 0 = unlimited          (default: 0)
    DEVICE_NAME       prefix on uploaded filenames            (default: $(hostname))
    UPLOAD_SCRIPT     path to capture-and-upload.sh
                                                              (default: ./capture-and-upload.sh)
    LEARNING_RATE     MOG2 learningRate, 0..1. Lower = slower
                      adaptation, more sensitive to slow change
                                                              (default: 0.001)

Usage:
    sudo systemctl stop fioup     # release /dev/video0 from the inference container
    EI_API_KEY=ei_xxx ./scripts/motion-watcher.py

Camera note: only one process can hold /dev/video0 at a time.
"""

import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import cv2  # type: ignore
except ImportError:
    sys.exit("missing dep: sudo apt install -y python3-opencv  (or pip install opencv-python)")


def env(name: str, default=None, *, required: bool = False, cast=str):
    val = os.environ.get(name, default)
    if required and not val:
        sys.exit(f"{name} is required")
    if val is None:
        return None
    try:
        return cast(val)
    except (TypeError, ValueError):
        sys.exit(f"{name} must be {cast.__name__}, got {val!r}")


EI_API_KEY     = env("EI_API_KEY", required=True)
THRESHOLD      = env("THRESHOLD", "1.5", cast=float)        # percent
MIN_AREA       = env("MIN_AREA", "5000", cast=int)          # pixels
COOLDOWN       = env("COOLDOWN", "10", cast=float)
WARMUP         = env("WARMUP", "5", cast=float)
CATEGORY       = env("CATEGORY", "training")
LABEL          = env("LABEL", "motion")
DEVICE         = env("DEVICE", "/dev/video0")
MAX_UPLOADS    = env("MAX_UPLOADS", "0", cast=int)
DEVICE_NAME    = env("DEVICE_NAME", socket.gethostname())
UPLOAD_SCRIPT  = env("UPLOAD_SCRIPT", str(Path(__file__).with_name("capture-and-upload.sh")))
LEARNING_RATE  = env("LEARNING_RATE", "0.001", cast=float)

if CATEGORY not in ("training", "testing"):
    sys.exit("CATEGORY must be 'training' or 'testing'")
if not Path(UPLOAD_SCRIPT).is_file():
    sys.exit(f"upload script not found: {UPLOAD_SCRIPT}")

device_index_env = os.environ.get("DEVICE_INDEX")
if device_index_env is not None:
    cap_arg = int(device_index_env)
else:
    m = re.search(r"(\d+)$", DEVICE)
    cap_arg = int(m.group(1)) if m else DEVICE  # type: ignore[assignment]


def trigger_upload(frame_path: str) -> bool:
    cmd_env = {
        **os.environ,
        "EI_API_KEY":  EI_API_KEY,
        "IMAGE_FILE":  frame_path,
        "LABEL":       LABEL,
        "CATEGORY":    CATEGORY,
        "DEVICE_NAME": DEVICE_NAME,
    }
    return subprocess.run([UPLOAD_SCRIPT], env=cmd_env).returncode == 0


def main() -> None:
    print(f"[motion] threshold={THRESHOLD}% min_area={MIN_AREA}px² "
          f"cooldown={COOLDOWN}s warmup={WARMUP}s")
    print(f"[motion] category={CATEGORY} label={LABEL} device={DEVICE}")

    stop = {"now": False}

    def shutdown(_signum, _frame):
        stop["now"] = True
        print("\n[motion] shutting down...")

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    cap = cv2.VideoCapture(cap_arg)  # type: ignore[arg-type]
    if not cap.isOpened():
        sys.exit(f"failed to open camera at {DEVICE}")

    backsub = cv2.createBackgroundSubtractorMOG2(
        history=500, varThreshold=16, detectShadows=False
    )

    started = time.time()
    last_trigger = 0.0
    uploads = 0

    try:
        while not stop["now"]:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.2)
                continue

            fgmask = backsub.apply(frame, learningRate=LEARNING_RATE)
            # Clean up speckle / shadow noise.
            fgmask = cv2.morphologyEx(
                fgmask, cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
            )

            total_px = fgmask.size
            fg_px = int((fgmask > 0).sum())
            motion_pct = 100.0 * fg_px / total_px

            largest_blob = 0
            if motion_pct >= THRESHOLD:
                contours, _ = cv2.findContours(
                    fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                )
                if contours:
                    largest_blob = int(max(cv2.contourArea(c) for c in contours))

            elapsed = time.time() - started
            if elapsed < WARMUP:
                sys.stdout.write(f"\r[motion] warming up… {elapsed:.1f}/{WARMUP:.1f}s     ")
                sys.stdout.flush()
                continue

            now = time.time()
            triggered = (
                motion_pct >= THRESHOLD
                and largest_blob >= MIN_AREA
                and (now - last_trigger) >= COOLDOWN
            )

            if triggered:
                last_trigger = now
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
                    cv2.imwrite(tf.name, frame)
                    path = tf.name
                print(f"[motion] {motion_pct:.2f}% / blob={largest_blob}px² → uploading")
                if trigger_upload(path):
                    uploads += 1
                try:
                    os.unlink(path)
                except OSError:
                    pass
                if MAX_UPLOADS and uploads >= MAX_UPLOADS:
                    print(f"[motion] reached MAX_UPLOADS={MAX_UPLOADS}, exiting")
                    break
            else:
                sys.stdout.write(
                    f"\r[motion] motion={motion_pct:5.2f}%  "
                    f"largest_blob={largest_blob:>6}px²    "
                )
                sys.stdout.flush()
    finally:
        cap.release()

    print(f"\n[motion] done. {uploads} sample(s) uploaded to {CATEGORY}.")


if __name__ == "__main__":
    main()
