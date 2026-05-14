#!/usr/bin/env python3

from flask import Flask, render_template_string, send_from_directory, abort, request, redirect, url_for
from pathlib import Path
from datetime import datetime
import subprocess
import shutil
import math
import re
import cv2


app = Flask(__name__)

CAPTURE_DIR = Path.home() / "birdcam" / "captures"
THUMB_DIR = Path.home() / "birdcam" / "gallery" / "thumbs"

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

DEFAULT_PER_PAGE = 24
MAX_PER_PAGE = 96

THUMB_WIDTH = 420
THUMB_JPEG_QUALITY = 80

THUMB_DIR.mkdir(parents=True, exist_ok=True)


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
            --danger: #e74c3c;
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

        .filters,
        .pagination,
        .per-page {
            margin-top: 0.9rem;
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
            align-items: center;
        }

        .filter,
        .page-link,
        .per-page a {
            color: var(--text);
            background: var(--panel2);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.45rem 0.75rem;
            text-decoration: none;
            font-size: 0.85rem;
        }

        .filter.active,
        .page-link.active,
        .per-page a.active {
            background: #eee;
            color: #111;
            border-color: #eee;
        }

        .page-link.disabled {
            opacity: 0.35;
            pointer-events: none;
        }

        .status-panel {
            margin-top: 0.9rem;
            display: flex;
            gap: 0.65rem;
            flex-wrap: wrap;
            color: #ddd;
            font-size: 0.85rem;
        }

        .status-item {
            background: var(--panel2);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.45rem 0.7rem;
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .status-dot {
            width: 0.65rem;
            height: 0.65rem;
            border-radius: 50%;
            display: inline-block;
        }

        .status-dot.ok {
            background: var(--bird);
        }

        .status-dot.bad {
            background: var(--danger);
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

.delete-form {
    margin-top: 0.7rem;
}

.delete-button {
    width: 100%;
    color: #eee;
    background: #3a1f1f;
    border: 1px solid #703030;
    border-radius: 999px;
    padding: 0.45rem 0.7rem;
    font-size: 0.82rem;
    cursor: pointer;
}

.delete-button:hover {
    background: #5a2a2a;
}
    </style>
</head>
<body>

<header>
    <h1>Birdcam Gallery</h1>

    <div class="subtitle">
        {{ count }} picture{{ "" if count == 1 else "s" }} shown ·
        {{ filtered_total }} matching ·
        {{ total }} total ·
        page {{ page }} / {{ total_pages }}
    </div>

    <div class="filters">
        <a class="filter {{ 'active' if mode == 'all' else '' }}" href="/?filter=all&per_page={{ per_page }}">All</a>
        <a class="filter {{ 'active' if mode == 'bird' else '' }}" href="/?filter=bird&per_page={{ per_page }}">Birds</a>
        <a class="filter {{ 'active' if mode == 'motion' else '' }}" href="/?filter=motion&per_page={{ per_page }}">Motion only</a>
    </div>

    <div class="pagination">
        <a class="page-link {{ 'disabled' if page <= 1 else '' }}"
           href="/?filter={{ mode }}&page={{ page - 1 }}&per_page={{ per_page }}">
            Previous
        </a>

        {% for p in page_numbers %}
            <a class="page-link {{ 'active' if p == page else '' }}"
               href="/?filter={{ mode }}&page={{ p }}&per_page={{ per_page }}">
                {{ p }}
            </a>
        {% endfor %}

        <a class="page-link {{ 'disabled' if page >= total_pages else '' }}"
           href="/?filter={{ mode }}&page={{ page + 1 }}&per_page={{ per_page }}">
            Next
        </a>
    </div>

    <div class="per-page">
        <span style="color:#aaa;font-size:0.85rem;">Per page:</span>
        {% for n in [12, 24, 48, 96] %}
            <a class="{{ 'active' if n == per_page else '' }}"
               href="/?filter={{ mode }}&page=1&per_page={{ n }}">
                {{ n }}
            </a>
        {% endfor %}
    </div>

    <div class="status-panel">
         <div class="status-item">
            Birds: {{ status.bird_count }}
        </div>

        <div class="status-item">
            Motion: {{ status.motion_count }}
        </div>
        <div class="status-item">
            Latest: {{ status.latest_date }}
        </div>

        <div class="status-item">
            <span class="status-dot {{ 'ok' if status.birdcam_service.active else 'bad' }}"></span>
            Camera: {{ status.birdcam_service.status }}
        </div>

         <div class="status-item">
            Disk: {{ status.free_gb }} GB free / {{ status.total_gb }} GB · {{ status.used_percent }}% used
        </div>
    </div>
</header>

{% if images %}
<main class="gallery">
    {% for image in images %}
    <div class="card">
    <span class="badge {{ image.kind_class }}">{{ image.kind_label }}</span>

    <a href="/image/{{ image.name }}" target="_blank">
        <img src="/thumb/{{ image.name }}" loading="lazy" alt="{{ image.name }}">
    </a>

    <div class="meta">
        <div class="filename">{{ image.name }}</div>

        <div class="details">
            <div>{{ image.date }}</div>
            <div>Best: {{ image.best_label }}</div>
            <div>Confidence: {{ image.confidence }}</div>
            <div>Motion score: {{ image.motion_score }}</div>
        </div>

        <form
            method="post"
            action="/delete/{{ image.name }}"
            onsubmit="return confirm('Delete this picture?');"
            class="delete-form"
        >
            <input type="hidden" name="filter" value="{{ mode }}">
            <input type="hidden" name="page" value="{{ page }}">
            <input type="hidden" name="per_page" value="{{ per_page }}">
            <button type="submit" class="delete-button">Delete</button>
        </form>
    </div>
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

    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime)

    return {
        "name": name,
        "kind": kind,
        "kind_label": kind_label,
        "kind_class": kind_class,
        "confidence": confidence,
        "best_label": best_label,
        "motion_score": motion_score,
        "date": modified.strftime("%Y-%m-%d %H:%M:%S"),
        "mtime": stat.st_mtime,
    }


def get_all_images():
    if not CAPTURE_DIR.exists():
        return []

    files = [
        path for path in CAPTURE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS
    ]

    images = [parse_image_metadata(path) for path in files]
    images.sort(key=lambda item: item["mtime"], reverse=True)

    return images


def filter_images(images, mode: str):
    if mode == "bird":
        return [image for image in images if image["kind"] == "bird"]

    if mode == "motion":
        return [image for image in images if image["kind"] == "motion"]

    return images


def paginate_images(images, page: int, per_page: int):
    total = len(images)
    total_pages = max(1, math.ceil(total / per_page))

    page = max(1, min(page, total_pages))

    start = (page - 1) * per_page
    end = start + per_page

    return images[start:end], page, total_pages


def make_page_numbers(page: int, total_pages: int):
    if total_pages <= 7:
        return list(range(1, total_pages + 1))

    candidates = {1, 2, total_pages - 1, total_pages}

    for p in range(page - 2, page + 3):
        if 1 <= p <= total_pages:
            candidates.add(p)

    return sorted(candidates)


def service_status(service_name: str):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=2,
        )
        status = result.stdout.strip()
    except Exception:
        status = "unknown"

    return {
        "name": service_name,
        "active": status == "active",
        "status": status,
    }


def build_status(all_images):
    if all_images:
        latest = all_images[0]
        latest_name = latest["name"]
        latest_date = latest["date"]
    else:
        latest_name = "none"
        latest_date = "n/a"

    disk = shutil.disk_usage(CAPTURE_DIR if CAPTURE_DIR.exists() else Path.home())

    free_gb = disk.free / (1024 ** 3)
    total_gb = disk.total / (1024 ** 3)
    used_percent = (disk.used / disk.total) * 100

    return {
        "birdcam_service": service_status("birdcam"),
        "bird_count": sum(1 for image in all_images if image["kind"] == "bird"),
        "motion_count": sum(1 for image in all_images if image["kind"] == "motion"),
        "latest_name": latest_name,
        "latest_date": latest_date,
        "free_gb": f"{free_gb:.1f}",
        "total_gb": f"{total_gb:.1f}",
        "used_percent": f"{used_percent:.0f}",
    }


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

def delete_image_and_thumbnail(filename: str):
    image_path = safe_image_path(filename)
    thumb_path = thumb_path_for(filename)

    if image_path.exists():
        image_path.unlink()

    if thumb_path.exists():
        thumb_path.unlink()

def thumb_path_for(filename: str):
    safe_name = filename.replace("/", "_")
    return THUMB_DIR / safe_name


def ensure_thumbnail(filename: str):
    source = safe_image_path(filename)
    thumb = thumb_path_for(filename)

    if thumb.exists() and thumb.stat().st_mtime >= source.stat().st_mtime:
        return thumb

    img = cv2.imread(str(source))

    if img is None:
        abort(404)

    height, width = img.shape[:2]

    if width > THUMB_WIDTH:
        ratio = THUMB_WIDTH / width
        new_size = (THUMB_WIDTH, int(height * ratio))
        img = cv2.resize(img, new_size, interpolation=cv2.INTER_AREA)

    ok = cv2.imwrite(
        str(thumb),
        img,
        [int(cv2.IMWRITE_JPEG_QUALITY), THUMB_JPEG_QUALITY],
    )

    if not ok:
        abort(500)

    return thumb


def parse_int_arg(name: str, default: int, minimum: int, maximum: int):
    raw = request.args.get(name, str(default))

    try:
        value = int(raw)
    except ValueError:
        value = default

    return max(minimum, min(value, maximum))


@app.route("/")
def index():
    mode = request.args.get("filter", "all")

    if mode not in {"all", "bird", "motion"}:
        mode = "all"

    page = parse_int_arg("page", 1, 1, 100000)
    per_page = parse_int_arg("per_page", DEFAULT_PER_PAGE, 1, MAX_PER_PAGE)

    all_images = get_all_images()
    filtered_images = filter_images(all_images, mode)

    page_images, page, total_pages = paginate_images(filtered_images, page, per_page)
    page_numbers = make_page_numbers(page, total_pages)

    status = build_status(all_images)

    return render_template_string(
        HTML_TEMPLATE,
        images=page_images,
        count=len(page_images),
        total=len(all_images),
        filtered_total=len(filtered_images),
        page=page,
        total_pages=total_pages,
        page_numbers=page_numbers,
        per_page=per_page,
        mode=mode,
        status=status,
        capture_dir=str(CAPTURE_DIR),
    )


@app.route("/image/<path:filename>")
def image(filename):
    safe_image_path(filename)
    return send_from_directory(CAPTURE_DIR, filename)


@app.route("/thumb/<path:filename>")
def thumb(filename):
    thumb = ensure_thumbnail(filename)
    return send_from_directory(THUMB_DIR, thumb.name)


@app.route("/clear-thumbs")
def clear_thumbs():
    for path in THUMB_DIR.iterdir():
        if path.is_file():
            path.unlink()

    return redirect(url_for("index"))

@app.route("/delete/<path:filename>", methods=["POST"])
def delete_image(filename):
    mode = request.form.get("filter", "all")
    page = request.form.get("page", "1")
    per_page = request.form.get("per_page", str(DEFAULT_PER_PAGE))

    if mode not in {"all", "bird", "motion"}:
        mode = "all"

    delete_image_and_thumbnail(filename)

    return redirect(
        url_for(
            "index",
            filter=mode,
            page=page,
            per_page=per_page,
        )
    )

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
    )
