#!/usr/bin/env python3
"""
anomaly-watcher.py — run a visual anomaly detection .eim against the
UNO Q's camera and, when an anomaly fires, hand the frame to
capture-and-upload.sh so it lands in the Edge Impulse training (or
testing) dataset.

Why: the main object-detection model in this repo only retrains on new
labeled data. Pointing a separate visual-anomaly model at the live
camera turns "interesting" moments into automatic training samples —
active learning without anyone watching the camera.

Architecture
------------
    /dev/video0
        │
        ▼
    [anomaly .eim] ── score >= THRESHOLD ──► capture-and-upload.sh ──► EI ingestion
                                                                          │
                                                                          ▼
                                                            ei-data-watch-and-retrain.yml

Prerequisites on the device:
    sudo apt install -y python3-pip python3-opencv ffmpeg
    pip3 install --user edge_impulse_linux

Required env:
    EI_API_KEY        Edge Impulse API key for the *target* project
                      (the project that should receive the captured
                      frames — typically the object-detection project,
                      not the anomaly project).
    ANOMALY_MODEL     Path to your visual-anomaly .eim file. Build it
                      from your anomaly project with the arduino-uno-q
                      target — same flow as the main model. Drop it
                      next to this script (default: ./anomaly.eim).

Optional env:
    THRESHOLD         visual_anomaly_max score that fires a capture
                                                          (default: 5.0)
    COOLDOWN          seconds to wait after a capture before another
                                                          (default: 10)
    CATEGORY          training | testing                  (default: training)
    LABEL             x-label sent with each upload       (default: anomaly)
    DEVICE            V4L2 device path                    (default: /dev/video0)
    DEVICE_INDEX      cv2 device index (overrides DEVICE) (default: derived)
    MAX_UPLOADS       stop after this many captures (0 = unlimited)
                                                          (default: 0)
    DEVICE_NAME       prefix on uploaded filenames        (default: $(hostname))
    UPLOAD_SCRIPT     path to capture-and-upload.sh       (default: alongside this file)

Usage:
    EI_API_KEY=ei_xxx ANOMALY_MODEL=./anomaly.eim ./scripts/anomaly-watcher.py

Camera note: only one process can hold /dev/video0. Stop the inference
container (`sudo systemctl stop fioup`) before running this, or use a
second UVC camera and set DEVICE=/dev/video1.
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

try:
    from edge_impulse_linux.image import ImageImpulseRunner  # type: ignore
except ImportError:
    sys.exit("missing dep: pip3 install --user edge_impulse_linux")


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
ANOMALY_MODEL  = env("ANOMALY_MODEL", str(Path(__file__).with_name("anomaly.eim")))
THRESHOLD      = env("THRESHOLD", "5.0", cast=float)
COOLDOWN       = env("COOLDOWN", "10", cast=float)
CATEGORY       = env("CATEGORY", "training")
LABEL          = env("LABEL", "anomaly")
DEVICE         = env("DEVICE", "/dev/video0")
MAX_UPLOADS    = env("MAX_UPLOADS", "0", cast=int)
DEVICE_NAME    = env("DEVICE_NAME", socket.gethostname())
UPLOAD_SCRIPT  = env("UPLOAD_SCRIPT", str(Path(__file__).with_name("capture-and-upload.sh")))

if CATEGORY not in ("training", "testing"):
    sys.exit("CATEGORY must be 'training' or 'testing'")
if not Path(ANOMALY_MODEL).is_file():
    sys.exit(f"anomaly model not found: {ANOMALY_MODEL}")
if not Path(UPLOAD_SCRIPT).is_file():
    sys.exit(f"upload script not found: {UPLOAD_SCRIPT}")

# cv2.VideoCapture takes either an int index or a string device path.
device_index_env = os.environ.get("DEVICE_INDEX")
if device_index_env is not None:
    cap_arg = int(device_index_env)
else:
    m = re.search(r"(\d+)$", DEVICE)
    cap_arg = int(m.group(1)) if m else DEVICE  # type: ignore[assignment]


def trigger_upload(frame_path: str) -> bool:
    cmd_env = {
        **os.environ,
        "EI_API_KEY":   EI_API_KEY,
        "IMAGE_FILE":   frame_path,
        "LABEL":        LABEL,
        "CATEGORY":     CATEGORY,
        "DEVICE_NAME":  DEVICE_NAME,
    }
    return subprocess.run([UPLOAD_SCRIPT], env=cmd_env).returncode == 0


def main() -> None:
    print(f"[watcher] model={ANOMALY_MODEL}")
    print(f"[watcher] threshold={THRESHOLD} cooldown={COOLDOWN}s "
          f"category={CATEGORY} label={LABEL} device={DEVICE}")

    stop = {"now": False}

    def shutdown(_signum, _frame):
        stop["now"] = True
        print("\n[watcher] shutting down...")

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    cap = cv2.VideoCapture(cap_arg)  # type: ignore[arg-type]
    if not cap.isOpened():
        sys.exit(f"failed to open camera at {DEVICE}")

    last_trigger = 0.0
    uploads = 0

    with ImageImpulseRunner(ANOMALY_MODEL) as runner:
        info = runner.init()
        proj = info.get("project", {})
        print(f"[watcher] loaded {proj.get('owner','?')}/{proj.get('name','?')} v{proj.get('deploy_version','?')}")

        try:
            while not stop["now"]:
                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(0.2)
                    continue

                # edge_impulse_linux expects RGB
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                features, _cropped = runner.get_features_from_image(rgb)
                res = runner.classify(features)
                payload = res.get("result", {}) if isinstance(res, dict) else {}

                # FOMO-AD / GMM anomaly models surface scores under these keys.
                score = (
                    payload.get("visual_anomaly_max")
                    or payload.get("anomaly")
                    or 0.0
                )

                now = time.time()
                if score >= THRESHOLD and (now - last_trigger) >= COOLDOWN:
                    last_trigger = now
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
                        cv2.imwrite(tf.name, frame)
                        path = tf.name
                    print(f"[watcher] anomaly score={score:.3f} ≥ {THRESHOLD} → uploading")
                    if trigger_upload(path):
                        uploads += 1
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
                    if MAX_UPLOADS and uploads >= MAX_UPLOADS:
                        print(f"[watcher] reached MAX_UPLOADS={MAX_UPLOADS}, exiting")
                        break
                else:
                    sys.stdout.write(f"\r[watcher] score={score:.3f}        ")
                    sys.stdout.flush()
        finally:
            cap.release()

    print(f"\n[watcher] done. {uploads} sample(s) uploaded to {CATEGORY}.")


if __name__ == "__main__":
    main()
