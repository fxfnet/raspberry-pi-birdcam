# Raspberry Pi Birdcam

A lightweight Raspberry Pi bird feeder camera.

The camera continuously watches for movement, saves all motion-triggered pictures, and tags each picture depending on whether a bird was recognized by an OpenCV DNN model.

The project also includes a small Flask web gallery to browse captured pictures from the Raspberry Pi.

## Hardware

Tested with:

- Raspberry Pi 3 Model B v1.2
- Raspberry Pi Camera Module v1 / OV5647 CSI camera
- Raspberry Pi OS / Debian Trixie
- Python 3.13
- OpenCV DNN
- Picamera2

## Features

- Continuous camera capture
- Motion detection
- Burst capture after movement
- Bird detection using MobileNet SSD via OpenCV DNN
- Optional species identification using Google AIY Vision Birds V1 (964 species, iNaturalist)
- Filename tagging:
  - `bird_...jpg` when a bird is detected
  - `bird_..._sp{species}_spconf{score}.jpg` when a species is identified
  - `motion_...jpg` when movement is detected but no bird is recognized
- Local web gallery
- Optional systemd autorun

## Project structure

```text
birdcam/
├── birdcam_motion.py
├── gallery/
│   └── app.py
├── scripts/
│   ├── install_models.sh
│   ├── install_services.sh
│   └── stop_services.sh
├── systemd/
│   ├── birdcam.service
│   └── birdcam-gallery.service
├── model/
└── captures/
```

## Install dependencies

On Raspberry Pi OS / Debian:

```bash
sudo apt update
sudo apt install -y \
  python3-picamera2 \
  python3-opencv \
  python3-numpy \
  python3-flask \
  wget
```

## Install the AI models

```bash
./scripts/install_models.sh
```

This downloads:
- the MobileNet SSD Caffe model (bird detection, OpenCV DNN)
- the Google AIY Vision Birds V1 TFLite model (species identification, 964 species)

Install the TFLite runtime for species identification (optional):

pip install ai-edge-litert

If `ai-edge-litert` is not available for your Python version, try `pip install tflite-runtime`.
Species identification is disabled gracefully if the package or model files are missing.

## Run the birdcam manually

```bash
python3 birdcam_motion.py
```

Captured pictures are stored in:

```
~/birdcam/captures
```

## Run the web gallery manually

```bash
python3 gallery/app.py
```

Then open:

http://raspberrypi.local:5000

or:

http://<raspberry-pi-ip>:5000

## Install autorun services

```bash
./scripts/install_services.sh
```

Start services:

```bash
sudo systemctl start birdcam
sudo systemctl start birdcam-gallery
```

Check status:

```bash
systemctl status birdcam
systemctl status birdcam-gallery
```

View logs:

```bash
journalctl -u birdcam -f
journalctl -u birdcam-gallery -f
```

## Tuning

Main settings are inside birdcam_motion.py.

Useful parameters:

```
MOTION_THRESHOLD = 1200
BIRD_CONFIDENCE_THRESHOLD = 0.45
SPECIES_CONFIDENCE_THRESHOLD = 0.10
MIN_SECONDS_BETWEEN_SHOTS = 1.0
BURST_COUNT = 4
BURST_INTERVAL_SECONDS = 0.25
CAMERA_SIZE = (1280, 960)
```

If too many false movements are captured, increase:

```
MOTION_THRESHOLD
```

If birds are missed, decrease:

```
BIRD_CONFIDENCE_THRESHOLD
```

If the bird is too fast, increase:

```
BURST_COUNT
```

or reduce:

```
BURST_INTERVAL_SECONDS
```

## Notes

Bird detection uses OpenCV DNN (MobileNet SSD) which requires no extra runtime beyond `python3-opencv`.

Species identification uses a separate TFLite model and requires `ai-edge-litert` (or `tflite-runtime`).
These packages may not have pre-built wheels for Python 3.13 on Debian Trixie yet; the feature degrades gracefully if they are unavailable.

On Raspberry Pi OS/Debian, it is better to install via apt:

```bash
sudo apt install -y python3-picamera2 python3-opencv python3-numpy python3-flask
```
