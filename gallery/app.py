#!/usr/bin/env python3

from flask import Flask, render_template_string, send_from_directory, abort, request
from pathlib import Path
from datetime import datetime
import re

app = Flask(__name__)

CAPTURE_DIR = Path.home() / "birdcam" / "captures"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Birdcam Gallery</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <style>
        :root {
            --bg: #101010;
            --panel: #1b1b1b;
            --panel2: #242424;
            --border: #333;
            --text: #eee;
            --muted: #aaa;
            --bird: #2ecc71;
            --motion: #f39c12;
        }

        body {
            margin: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: var(--bg);
            color: var(--text);
        }

        header {
            padding: 1.2rem;
            background: var(--panel);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 10;
        }

        h1 {
            margin: 0;
            font-size: 1.4rem;
        }

        .subtitle {
            margin-top: 0.35rem;
            color: var(--muted);
            font-size: 0.9rem;
        }

        .filters {
            margin-top: 0.9rem;
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }

        .filter {
            color: var(--text);
            background: var(--panel2);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.45rem 0.75rem;
            text-decoration: none;
            font-size: 0.85rem;
        }

        .filter.active {
            background: #eee;
            color: #111;
            border-color: #eee;
        }

        .gallery {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
            gap: 14px;
            padding: 14px;
        }

        .card {
            position: relative;
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 18px rgba(0,0,0,0.35);
        }

        .card a {
            display: block;
            text-decoration: none;
            color: inherit;
        }

        .card img {
            width: 100%;
            height: 185px;
            object-fit: cover;
            display: block;
            background: #222;
        }

        .badge {
            position: absolute;
            top: 10px;
            left: 10px;
            padding: 0.32rem 0.55rem;
            border-radius: 999px;
            color: #111;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            box-shadow: 0 2px 10px rgba(0,0,0,0.35);
        }

        .badge.bird {
            background: var(--bird);
        }

        .badge.motion {
            background: var(--motion);
        }

        .meta {
            padding: 0.75rem;
            font-size: 0.83rem;
            color: #ccc;
        }

        .filename {
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: #fff;
            font-weight: 600;
        }

        .details {
            margin-top: 0.35rem;
            display: grid;
            gap: 0.15rem;
            color: #aaa;
        }

        .empty {
            padding: 2rem;
            color: #aaa;
        }

        footer {
            padding: 1rem;
            color: #777;
            font-size: 0.8rem;
            text-align: center;
        }
    </style>
</head>
<body>

<header>
    <h1>Birdcam Gallery</h1>
    <div class="subtitle">
        {{ count }} picture{{ "" if count == 1 else "s" }} shown · {{ total }} total · newest first
    </div>

    <div class="filters">
        <a class="filter {{ 'active' if mode == 'all' else '' }}" href="/">All</a>
        <a class="filter {{ 'active' if mode == 'bird' else '' }}" href="/?filter=bird">Birds</a>
        <a class="filter {{ 'active' if mode == 'motion' else '' }}" href="/?filter=motion">Motion only</a>
    </div>
</header>

{% if images %}
<main class="gallery">
    {% for image in images %}
    <div class="card">
        <a href="/image/{{ image.name }}" target="_blank">
            <span class="badge {{ image.kind_class }}">{{ image.kind_label }}</span>
            <img src="/thumb/{{ image.name }}" loading="lazy" alt="{{ image.name }}">
            <div class="meta">
                <div class="filename">{{ image.name }}</div>
                <div class="details">
                    <div>{{ image.date }}</div>
                    <div>Best: {{ image.best_label }}</div>
                    <div>Confidence: {{ image.confidence }}</div>
                    <div>Motion score: {{ image.motion_score }}</div>
                </div>
            </div>
        </a>
    </div>
    {% endfor %}
</main>
{% else %}
<div class="empty">
    No pictures found for this filter in {{ capture_dir }}.
</div>
{% endif %}

<footer>
    Raspberry Pi Birdcam
</footer>

</body>
</html>
"""


def parse_image_metadata(path: Path):
    name = path.name

    if name.startswith("bird_"):
        kind = "bird"
        kind_label = "BIRD"
        kind_class = "bird"
    elif name.startswith("motion_"):
        kind = "motion"
        kind_label = "MOTION"
        kind_class = "motion"
    else:
        kind = "unknown"
        kind_label = "PHOTO"
        kind_class = "motion"

    confidence_match = re.search(r"_conf([0-9.]+)", name)
    best_match = re.search(r"_best([a-zA-Z0-9_-]+)", name)
    motion_match = re.search(r"_motion([0-9]+)", name)

    confidence = confidence_match.group(1) if confidence_match else "n/a"
    best_label = best_match.group(1) if best_match else "n/a"
    motion_score = motion_match.group(1) if motion_match else "n/a"

    modified = datetime.fromtimestamp(path.stat().st_mtime)

    return {
        "name": name,
        "kind": kind,
        "kind_label": kind_label,
        "kind_class": kind_class,
        "confidence": confidence,
        "best_label": best_label,
        "motion_score": motion_score,
        "date": modified.strftime("%Y-%m-%d %H:%M:%S"),
        "mtime": path.stat().st_mtime,
    }


def list_images(mode: str):
    if not CAPTURE_DIR.exists():
        return [], 0

    files = [
        path for path in CAPTURE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS
    ]

    images = [parse_image_metadata(path) for path in files]
    images.sort(key=lambda item: item["mtime"], reverse=True)

    total = len(images)

    if mode == "bird":
        images = [image for image in images if image["kind"] == "bird"]
    elif mode == "motion":
        images = [image for image in images if image["kind"] == "motion"]

    return images, total


def safe_image_path(filename):
    path = CAPTURE_DIR / filename

    try:
        path.resolve().relative_to(CAPTURE_DIR.resolve())
    except ValueError:
        abort(403)

    if not path.exists() or not path.is_file():
        abort(404)

    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        abort(403)

    return path


@app.route("/")
def index():
    mode = request.args.get("filter", "all")

    if mode not in {"all", "bird", "motion"}:
        mode = "all"

    images, total = list_images(mode)

    return render_template_string(
        HTML_TEMPLATE,
        images=images,
        count=len(images),
        total=total,
        mode=mode,
        capture_dir=str(CAPTURE_DIR),
    )


@app.route("/image/<path:filename>")
def image(filename):
    safe_image_path(filename)
    return send_from_directory(CAPTURE_DIR, filename)


@app.route("/thumb/<path:filename>")
def thumb(filename):
    safe_image_path(filename)
    return send_from_directory(CAPTURE_DIR, filename)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
    )
