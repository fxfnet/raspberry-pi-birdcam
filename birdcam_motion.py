#!/usr/bin/env python3

import numpy as np
from picamera2 import Picamera2
from datetime import datetime
from pathlib import Path
from collections import deque
import cv2
import time
import sys
import re
import os


# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------

BASE_DIR = Path.home() / "birdcam"
CAPTURE_DIR = BASE_DIR / "captures"
MODEL_DIR = BASE_DIR / "model"

PROTOTXT_PATH = MODEL_DIR / "MobileNetSSD_deploy.prototxt"
MODEL_PATH = MODEL_DIR / "MobileNetSSD_deploy.caffemodel"

CAPTURE_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------
# Camera settings
# ------------------------------------------------------------

# Continuous capture resolution.
# We do NOT switch to still mode anymore, because switching modes is too slow
# for fast birds.
CAMERA_SIZE = (1280, 960)

# Motion detection is done on a smaller frame for speed.
MOTION_SIZE = (640, 480)


# ------------------------------------------------------------
# Timing settings
# ------------------------------------------------------------

LOOP_DELAY_SECONDS = 0.03
WARMUP_SECONDS = 2.0

# Keep a few recent frames in memory.
FRAME_BUFFER_SIZE = 30

# Use the latest frame when movement is detected.
# Earlier values like -4 can save a frame before the bird is visible.
FRAME_TO_SAVE_FROM_BUFFER = -1

# Allows several captures during a visit.
MIN_SECONDS_BETWEEN_SHOTS = 0.7

# Burst after motion detection.
# This increases the chance of catching fast birds.
BURST_COUNT = 8
BURST_INTERVAL_SECONDS = 0.12


# ------------------------------------------------------------
# Motion detection settings
# ------------------------------------------------------------

MOTION_THRESHOLD = 1200
PIXEL_DIFF_THRESHOLD = 30


# ------------------------------------------------------------
# Bird recognition settings
# ------------------------------------------------------------

BIRD_CONFIDENCE_THRESHOLD = 0.45
TARGET_LABEL = "bird"

CLASSES = [
    "background",
    "aeroplane",
    "bicycle",
    "bird",
    "boat",
    "bottle",
    "bus",
    "car",
    "cat",
    "chair",
    "cow",
    "diningtable",
    "dog",
    "horse",
    "motorbike",
    "person",
    "pottedplant",
    "sheep",
    "sofa",
    "train",
    "tvmonitor",
]


# ------------------------------------------------------------
# Safety checks
# ------------------------------------------------------------

if not PROTOTXT_PATH.exists():
    print(f"ERROR: model config not found: {PROTOTXT_PATH}", file=sys.stderr)
    sys.exit(1)

if not MODEL_PATH.exists():
    print(f"ERROR: model weights not found: {MODEL_PATH}", file=sys.stderr)
    sys.exit(1)


# ------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------

def safe_label(label: str) -> str:
    label = label.lower().strip()
    label = re.sub(r"[^a-z0-9_-]+", "_", label)
    return label or "none"


def atomic_rename(src: Path, dst: Path):
    os.replace(str(src), str(dst))

def save_rgb_jpeg(rgb_frame, filename: Path):
    """
    Save camera frame as JPEG with corrected colors.

    Correction déduite de la mire :
    - rouge et bleu inversés dans la chaîne actuelle ;
    - gains RGB simples issus de la comparaison avec le PDF ColorChecker.
    """

    color_gains = np.array((0.831, 0.883, 0.754), dtype=np.float32)

    # Correction principale : swap rouge / bleu.
    corrected_rgb = rgb_frame[:, :, [2, 1, 0]].astype(np.float32)

    # Correction secondaire : gains par canal.
    corrected_rgb = corrected_rgb * color_gains

    corrected_rgb = np.clip(corrected_rgb, 0, 255).astype(np.uint8)

    # OpenCV écrit en BGR.
    corrected_bgr = cv2.cvtColor(corrected_rgb, cv2.COLOR_RGB2BGR)

    cv2.imwrite(
        str(filename),
        corrected_bgr,
        [int(cv2.IMWRITE_JPEG_QUALITY), 90],
    )


def prepare_motion_gray(rgb_frame):
    """
    Prepare a small grayscale frame for motion detection.
    """
    small = cv2.resize(rgb_frame, MOTION_SIZE)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)
    return gray


# ------------------------------------------------------------
# Load OpenCV DNN model
# ------------------------------------------------------------

print("Loading OpenCV DNN model...")
net = cv2.dnn.readNetFromCaffe(str(PROTOTXT_PATH), str(MODEL_PATH))
print("Model loaded.")


def detect_bird(rgb_frame):
    """
    Detect whether the frame contains a bird.

    Input:
        rgb_frame: RGB frame from Picamera2

    Returns:
        bird_detected: bool
        best_label: str
        best_score: float
    """

    bgr_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)

    blob = cv2.dnn.blobFromImage(
        bgr_frame,
        scalefactor=0.007843,
        size=(300, 300),
        mean=127.5,
    )

    net.setInput(blob)
    detections = net.forward()

    bird_detected = False
    best_label = "none"
    best_score = 0.0

    for i in range(detections.shape[2]):
        confidence = float(detections[0, 0, i, 2])
        class_id = int(detections[0, 0, i, 1])

        if class_id < 0 or class_id >= len(CLASSES):
            continue

        label = CLASSES[class_id]

        if confidence > best_score:
            best_score = confidence
            best_label = label

        if label == TARGET_LABEL and confidence >= BIRD_CONFIDENCE_THRESHOLD:
            bird_detected = True

    return bird_detected, best_label, best_score


# ------------------------------------------------------------
# Camera setup
# ------------------------------------------------------------

picam2 = Picamera2()

camera_config = picam2.create_video_configuration(
    main={
        "size": CAMERA_SIZE,
        "format": "RGB888",
    },
    controls={
        "FrameRate": 20,
        "ExposureTime": 3000,
        "AnalogueGain": 4.0,
    }

)


# ------------------------------------------------------------
# Main loop
# ------------------------------------------------------------

previous_gray = None
last_capture_time = 0.0
frame_buffer = deque(maxlen=FRAME_BUFFER_SIZE)

try:
    print("Starting birdcam: motion capture burst + bird tagging.")
    print(f"Camera size: {CAMERA_SIZE}")
    print(f"Motion size: {MOTION_SIZE}")
    print(f"Frame buffer size: {FRAME_BUFFER_SIZE}")
    print(f"Frame saved from buffer index: {FRAME_TO_SAVE_FROM_BUFFER}")
    print(f"Burst count: {BURST_COUNT}")
    print(f"Burst interval: {BURST_INTERVAL_SECONDS}s")
    print(f"Min seconds between shots: {MIN_SECONDS_BETWEEN_SHOTS}")
    print(f"Motion threshold: {MOTION_THRESHOLD}")
    print(f"Bird confidence threshold: {BIRD_CONFIDENCE_THRESHOLD}")
    print(f"Captures directory: {CAPTURE_DIR}")

    picam2.configure(camera_config)
    picam2.start()

    time.sleep(WARMUP_SECONDS)

    print("Birdcam started. Press Ctrl+C to stop.")

    while True:
        frame = picam2.capture_array()
        frame_buffer.append(frame.copy())

        gray = prepare_motion_gray(frame)

        if previous_gray is None:
            previous_gray = gray
            time.sleep(LOOP_DELAY_SECONDS)
            continue

        delta = cv2.absdiff(previous_gray, gray)

        threshold_image = cv2.threshold(
            delta,
            PIXEL_DIFF_THRESHOLD,
            255,
            cv2.THRESH_BINARY,
        )[1]

        motion_score = cv2.countNonZero(threshold_image)
        now = time.time()

        motion_detected = motion_score > MOTION_THRESHOLD
        capture_allowed = now - last_capture_time > MIN_SECONDS_BETWEEN_SHOTS

        if motion_detected and capture_allowed and len(frame_buffer) >= 2:
            try:
                first_frame = frame_buffer[FRAME_TO_SAVE_FROM_BUFFER].copy()
            except IndexError:
                first_frame = frame_buffer[-1].copy()

            burst_frames = [first_frame]

            # Capture additional frames after the trigger.
            for _ in range(BURST_COUNT - 1):
                time.sleep(BURST_INTERVAL_SECONDS)
                burst_frames.append(picam2.capture_array().copy())

            for burst_index, burst_frame in enumerate(burst_frames):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

                temp_filename = CAPTURE_DIR / (
                    f"pending_{timestamp}"
                    f"_burst{burst_index}"
                    f"_motion{motion_score}.jpg"
                )

                # Save immediately before doing AI recognition.
                save_rgb_jpeg(burst_frame, temp_filename)

                bird_detected, best_label, best_score = detect_bird(burst_frame)

                label_for_filename = safe_label(best_label)
                confidence_for_filename = f"{best_score:.2f}"

                prefix = "bird" if bird_detected else "motion"

                final_filename = CAPTURE_DIR / (
                    f"{prefix}_{timestamp}"
                    f"_burst{burst_index}"
                    f"_motion{motion_score}"
                    f"_conf{confidence_for_filename}"
                    f"_best{label_for_filename}.jpg"
                )

                atomic_rename(temp_filename, final_filename)

                print(
                    f"Motion: {motion_score} | "
                    f"burst={burst_index} | "
                    f"AI best: {best_label} ({best_score:.2f}) | "
                    f"bird={bird_detected} | "
                    f"saved={final_filename.name}"
                )

            last_capture_time = time.time()
            previous_gray = None
            frame_buffer.clear()

            time.sleep(0.2)

        else:
            previous_gray = gray

        time.sleep(LOOP_DELAY_SECONDS)

except KeyboardInterrupt:
    print("\nStopping birdcam.")

except Exception as error:
    print(f"\nERROR: {error}", file=sys.stderr)
    raise

finally:
    try:
        picam2.stop()
    except Exception:
        pass

    try:
        picam2.close()
    except Exception:
        pass
