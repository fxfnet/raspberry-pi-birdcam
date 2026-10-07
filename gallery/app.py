#!/usr/bin/env python3

from flask import Flask, render_template_string, send_from_directory, abort, request, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from pathlib import Path
from datetime import datetime, date
import subprocess
import shutil
import re
import json
import cv2
import os
import threading
import time


app = Flask(__name__)
# Tailscale Funnel sert le site en https et relaie en http vers Flask :
# X-Forwarded-Proto rétablit https dans les URL absolues (og:url, og:image).
# x_for=0 : un client du réseau local ne peut pas falsifier son adresse dans les journaux.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1)

CAPTURE_DIR = Path.home() / "birdcam" / "captures"
THUMB_DIR = Path.home() / "birdcam" / "gallery" / "thumbs"
# À côté des captures, donc sur la clé USB quand captures/ est un lien vers elle.
CLIPS_DIR = CAPTURE_DIR.resolve().parent / "clips"
CLIP_SERVICE = "birdcam-clip"
CLIP_NAME_RE = re.compile(r"^clip_(\d{8})_(\d{6})\.mp4$")

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

DEFAULT_PER_PAGE = 24
MAX_PER_PAGE = 96

THUMB_WIDTH = 420
THUMB_JPEG_QUALITY = 80

# Public mode by default.
# Admin mode only when BIRDCAM_ADMIN=1 is set in the systemd service.
ADMIN_MODE = os.environ.get("BIRDCAM_ADMIN", "0") == "1"

THUMB_DIR.mkdir(parents=True, exist_ok=True)

# Noms français : chargés depuis training/species.json si présent.
# Clé = nom scientifique en minuscules (ex. "parus major"), valeur = nom français.
_SPECIES_JSON = Path(__file__).parent.parent / "training" / "species.json"
FRENCH_NAMES: dict[str, str] = {}
PARIS_SPECIES_LIST: list[dict] = []   # [{scientific, french}] trié par nom français
if _SPECIES_JSON.exists():
    _raw = json.loads(_SPECIES_JSON.read_text())
    for _sp in _raw:
        FRENCH_NAMES[_sp["scientific"].lower()] = _sp["french"]
    PARIS_SPECIES_LIST = sorted(_raw, key=lambda s: s["french"])

CORRECTIONS_PATH = Path.home() / "birdcam" / "corrections.json"

# Espèces étiquetées dès 0.3 (SPECIES_CONFIDENCE_THRESHOLD de birdcam_motion.py) ;
# en dessous de ce seuil, le badge est estompé et suivi de "?".
SPECIES_SURE_THRESHOLD = 0.6
CAMERA_TEST_IMAGE_PATH = Path.home() / "birdcam" / "camera_test.jpg"
CAMERA_TEST_STATUS_PATH = Path.home() / "birdcam" / "camera_test.json"


def french_name(display_name: str) -> str:
    """Retourne le nom français pour un nom affiché type 'Parus Major', ou '' si inconnu."""
    return FRENCH_NAMES.get(display_name.lower(), "")


def rank_species(images, limit: int):
    """
    Classement des espèces sur les photos bird_, avec les étiquettes sûres
    (>= SPECIES_SURE_THRESHOLD) et probables comptées séparément.
    """
    counts = {}
    for image in images:
        if image["kind"] == "bird" and image.get("species"):
            entry = counts.setdefault(image["species"], {"sure": 0, "probable": 0})
            entry["sure" if image["species_sure"] else "probable"] += 1
    ranked = sorted(counts.items(), key=lambda x: (x[1]["sure"] + x[1]["probable"], x[1]["sure"]), reverse=True)
    return [
        {"name": sp, "count": c["sure"] + c["probable"], "sure": c["sure"],
         "probable": c["probable"], "french": french_name(sp)}
        for sp, c in ranked[:limit]
    ]


_corrections_lock = threading.Lock()


def append_correction(image_name: str, was: str, now: str):
    from datetime import datetime
    entry = {"image": image_name, "was": was, "now": now,
             "corrected_at": datetime.now().isoformat(timespec="seconds")}
    # Verrou + écriture atomique : Flask sert les requêtes en threads, et
    # retag_history.py s'appuie sur ce fichier pour ne pas remettre une
    # espèce retirée à la main. Un fichier illisible n'est jamais écrasé.
    # resolve() : sur le Pi, corrections.json est un lien vers la clé USB ;
    # os.replace() sur le lien lui-même le remplacerait par un fichier local.
    target = CORRECTIONS_PATH.resolve()
    with _corrections_lock:
        data = []
        if target.exists():
            data = json.loads(target.read_text())
        data.append(entry)
        tmp_path = target.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        os.replace(tmp_path, target)


HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{{ "Birdcam Admin" if admin_mode else "Mangeoire Cam · Paris bird feeder" }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">

    {% if not admin_mode %}
    {% set og_title = "Mangeoire Cam · Paris bird feeder" %}
    {% set og_desc = "A Raspberry Pi watches a Paris bird feeder — " ~ status.bird_count ~ " bird pictures captured, species identified by AI." %}
    <meta property="og:type"        content="website">
    <meta property="og:url"         content="{{ base_url }}/">
    <meta property="og:title"       content="{{ og_title }}">
    <meta property="og:description" content="{{ og_desc }}">
    {% if og_image_name %}
    <meta property="og:image"        content="{{ base_url }}/image/{{ og_image_name }}">
    <meta property="og:image:width"  content="1280">
    <meta property="og:image:height" content="960">
    <meta property="og:image:alt"    content="Bird at the feeder">
    <meta name="twitter:card"        content="summary_large_image">
    <meta name="twitter:image"       content="{{ base_url }}/image/{{ og_image_name }}">
    {% else %}
    <meta name="twitter:card"        content="summary">
    {% endif %}
    <meta name="twitter:title"       content="{{ og_title }}">
    <meta name="twitter:description" content="{{ og_desc }}">
    {% endif %}

    <style>
        :root {
            --bg: #0d1110;
            --panel: #171d1b;
            --panel2: #222b27;
            --panel3: #101614;
            --border: #34413b;
            --text: #f2f1e8;
            --muted: #a9b3ad;
            --bird: #5fd38d;
            --motion: #f0b35a;
            --danger: #e46d5d;
            --blue: #70a7d8;
            --paper: #f4e7c5;
            --toysfab: #ffcf70;
        }

        body {
            margin: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background:
                radial-gradient(circle at top left, rgba(95, 211, 141, 0.12), transparent 34rem),
                radial-gradient(circle at top right, rgba(240, 179, 90, 0.10), transparent 30rem),
                var(--bg);
            color: var(--text);
        }

        header {
            padding: 1.2rem;
            background: rgba(23, 29, 27, 0.96);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 10;
            backdrop-filter: blur(8px);
            transition: padding 0.18s ease, box-shadow 0.18s ease;
        }

        header.compact {
            padding-top: 0.55rem;
            padding-bottom: 0.55rem;
            box-shadow: 0 4px 18px rgba(0,0,0,0.45);
        }

        header.compact h1 {
            font-size: 1rem;
        }

        header.compact .subtitle,
        header.compact .status-panel,
        header.compact .public-summary,
        header.compact .public-info,
        header.compact .admin-warning,
        header.compact .hero-intro {
            display: none;
        }

        header.compact .filters {
            margin-top: 0.45rem;
        }

        header.compact .filter {
            padding: 0.32rem 0.55rem;
            font-size: 0.78rem;
        }

        h1 {
            margin: 0;
            font-size: 1.45rem;
            letter-spacing: 0.01em;
        }

        .subtitle {
            margin-top: 0.35rem;
            color: var(--muted);
            font-size: 0.9rem;
        }

        .public-info {
            margin-top: 0.6rem;
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }

        .public-info-stats {
            font-size: 0.88rem;
            color: var(--text);
            display: flex;
            flex-wrap: wrap;
            gap: 0.2rem 0;
            align-items: center;
        }

        .public-info-stats .sep { color: var(--muted); margin: 0 0.3rem; }
        .public-info-stats .muted { color: var(--muted); }

        .public-info-species {
            font-size: 0.82rem;
            color: var(--muted);
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0;
        }

        .public-info-species a {
            color: var(--bird);
            text-decoration: none;
        }

        .public-info-species a:hover { text-decoration: underline; }
        .public-info-species .sp-count { margin: 0 0.15rem; }
        .public-info-species .sp-probable { color: var(--muted); font-style: italic; }
        .public-info-species .sep { color: var(--muted); }

        .bottom-nav {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            align-items: center;
            padding: 1rem 1rem 0.5rem;
        }

        .bottom-nav .muted { color: var(--muted); font-size: 0.85rem; }

        .hero-intro {
            margin-top: 0.7rem;
            max-width: 760px;
            color: #d8ded9;
            font-size: 0.92rem;
            line-height: 1.45;
        }

        .hero-intro a {
            color: var(--toysfab);
            text-decoration: none;
        }

        .hero-intro a:hover {
            text-decoration: underline;
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
            background: var(--paper);
            color: #111;
            border-color: var(--paper);
        }

        .page-link.disabled {
            opacity: 0.35;
            pointer-events: none;
        }

        .public-summary {
            margin-top: 0.9rem;
            color: #e7ece8;
            background: var(--panel2);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.45rem 0.75rem;
            display: inline-flex;
            font-size: 0.85rem;
            gap: 0.35rem;
            flex-wrap: wrap;
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

        .admin-warning {
            margin-top: 0.9rem;
            color: #111;
            background: var(--motion);
            border-radius: 10px;
            padding: 0.6rem 0.8rem;
            font-size: 0.9rem;
            font-weight: 700;
        }

        .latest-star {
            margin: 14px;
            background:
                linear-gradient(135deg, rgba(255, 207, 112, 0.14), rgba(95, 211, 141, 0.08)),
                var(--panel);
            border: 1px solid rgba(255, 207, 112, 0.4);
            border-radius: 18px;
            overflow: hidden;
            box-shadow: 0 8px 28px rgba(0,0,0,0.35);
        }

        .latest-star a {
            color: inherit;
            text-decoration: none;
        }

        .latest-star-inner {
            display: grid;
            grid-template-columns: minmax(0, 1.15fr) minmax(240px, 0.85fr);
            gap: 0;
        }

        .latest-star img {
            width: 100%;
            height: auto;
            max-height: 70vh;
            object-fit: contain;
            display: block;
            background: #222;
        }

        .latest-star-text {
            padding: 1.2rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }

        .latest-star-kicker {
            color: var(--toysfab);
            font-size: 0.82rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .latest-star-title {
            margin-top: 0.35rem;
            font-size: 1.45rem;
            font-weight: 800;
        }

        .latest-star-meta {
            margin-top: 0.45rem;
            /* Un nom d'espèce long ne doit pas élargir la carte. */
            overflow-wrap: anywhere;
            color: var(--muted);
            font-size: 0.9rem;
            line-height: 1.5;
        }

        .gallery {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
            gap: 14px;
            padding: 14px;
        }

        .card {
            position: relative;
            /* Retour de la visionneuse (#nom) : la carte ne passe pas sous le bandeau compact. */
            scroll-margin-top: 8rem;
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
            z-index: 2;
        }

        .badge.bird {
            background: var(--bird);
        }

        .badge.motion {
            background: var(--motion);
        }

        .badge.star {
            left: auto;
            right: 10px;
            background: var(--toysfab);
        }

        .meta {
            padding: 0.75rem;
            font-size: 0.83rem;
            color: #ccc;
        }

        .meta-species {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: #fff;
            font-weight: 600;
        }

        .meta-species .unknown {
            color: var(--muted);
            font-weight: 400;
        }

        /* Certitude de l'espèce : barre verte si sûre, ambre si probable. */
        .certainty {
            flex: 0 0 48px;
            height: 6px;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.12);
            overflow: hidden;
        }

        .certainty > span {
            display: block;
            height: 100%;
            background: var(--bird);
        }

        .certainty.probable > span {
            background: var(--motion);
        }

        .meta-time {
            margin-top: 0.25rem;
            color: var(--muted);
        }

        .burst {
            grid-column: 1 / -1;
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 10px;
            background: rgba(255, 255, 255, 0.02);
        }

        .burst-head {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            margin: 0 0 10px 4px;
            color: var(--muted);
            font-size: 0.85rem;
        }

        .burst-head strong {
            color: var(--text);
        }

        .burst-select {
            margin-left: auto;
            display: flex;
            align-items: center;
            gap: 0.35rem;
            cursor: pointer;
        }

        .burst-cards {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
            gap: 14px;
        }

        .admin-actions {
            margin-top: 0.75rem;
            display: grid;
            gap: 0.45rem;
        }

        .button-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.45rem;
        }

        .action-button {
            width: 100%;
            color: #eee;
            border-radius: 999px;
            padding: 0.45rem 0.7rem;
            font-size: 0.82rem;
            cursor: pointer;
        }

        .tag-button {
            background: #1f3140;
            border: 1px solid #375f80;
        }

        .tag-button:hover {
            background: #29445a;
        }

        .star-button {
            background: #3f351b;
            border: 1px solid #8d722d;
        }

        .star-button:hover {
            background: #5b4a22;
        }

        .delete-button {
            background: #3a1f1f;
            border: 1px solid #703030;
        }

        .delete-button:hover {
            background: #5a2a2a;
        }

        .species-err-button {
            background: #1f2e1f;
            border: 1px solid #3d5c3d;
        }

        .species-err-button:hover {
            background: #2a3f2a;
        }

        .card-cb-wrap {
            position: absolute;
            top: 0.5rem;
            right: 0.5rem;
            z-index: 3;
        }

        .card-cb-wrap input[type="checkbox"] {
            width: 1.25rem;
            height: 1.25rem;
            cursor: pointer;
            accent-color: var(--bird);
        }

        .card.selected {
            outline: 2px solid var(--bird);
            outline-offset: -1px;
        }

        /* display: flex ci-dessous l'emporterait sur l'attribut hidden. */
        .bulk-bar[hidden] {
            display: none;
        }

        .bulk-bar {
            position: fixed;
            bottom: 1rem;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(23, 29, 27, 0.97);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.45rem 0.75rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            flex-wrap: wrap;
            justify-content: center;
            z-index: 200;
            backdrop-filter: blur(12px);
            box-shadow: 0 4px 24px rgba(0,0,0,0.5);
            max-width: 90vw;
        }

        .bulk-count {
            font-size: 0.8rem;
            font-weight: 700;
            color: var(--bird);
            white-space: nowrap;
        }

        .bulk-btns {
            display: flex;
            gap: 0.3rem;
            flex-wrap: wrap;
        }

        .bk-btn {
            border-radius: 999px;
            padding: 0.28rem 0.65rem;
            font-size: 0.78rem;
            cursor: pointer;
            border: 1px solid transparent;
            color: #eee;
        }

        .bk-tag     { background: #1f3140; border-color: #375f80; }
        .bk-star    { background: #3f351b; border-color: #8d722d; }
        .bk-species { background: #1f2e1f; border-color: #3d5c3d; }
        .bk-del     { background: #3a1f1f; border-color: #703030; }
        .bk-cancel  { background: #1a1a1a; border-color: #444; }

        .bk-select {
            background: var(--panel2);
            border: 1px solid var(--border);
            border-radius: 999px;
            color: var(--text);
            font-size: 0.78rem;
            padding: 0.28rem 0.65rem;
            cursor: pointer;
            max-width: 160px;
        }

        .correct-species-wrap {
            margin-top: 0.5rem;
        }

        .correct-species-wrap summary {
            cursor: pointer;
            list-style: none;
            font-size: 0.75rem;
            color: var(--muted);
            opacity: 0.7;
        }

        .correct-species-wrap summary::-webkit-details-marker { display: none; }
        .correct-species-wrap summary:hover { opacity: 1; }

        .correct-species-form {
            margin-top: 0.4rem;
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
        }

        .correct-species-form select {
            width: 100%;
            background: var(--panel2);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text);
            font-size: 0.78rem;
            padding: 0.25rem 0.4rem;
        }

        .correct-species-form button {
            align-self: flex-start;
            background: #1f2e1f;
            border: 1px solid #3d5c3d;
            border-radius: 6px;
            color: #eee;
            font-size: 0.78rem;
            padding: 0.25rem 0.75rem;
            cursor: pointer;
        }


        .empty {
            padding: 2rem;
            color: #aaa;
        }

        .status-toggle {
            display: none;
            margin-top: 0.45rem;
            color: var(--text);
            background: var(--panel2);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.35rem 0.65rem;
            font-size: 0.78rem;
        }

        .camera-toggle-button {
            color: #111;
            border-radius: 999px;
            padding: 0.45rem 0.7rem;
            font-size: 0.85rem;
            font-weight: 700;
            cursor: pointer;
            border: none;
        }

        .camera-toggle-button.stop {
            background: var(--danger);
        }

        .camera-toggle-button.stop:hover {
            opacity: 0.85;
        }

        .camera-toggle-button.start {
            background: var(--bird);
        }

        .camera-toggle-button.start:hover {
            opacity: 0.85;
        }

        .camera-toggle-button.test {
            background: var(--muted);
        }

        .camera-toggle-button.test:hover {
            opacity: 0.85;
        }

        footer {
            padding: 1rem;
            color: #777;
            font-size: 0.8rem;
            text-align: center;
        }

        footer a {
            color: #aaa;
            text-decoration: none;
        }

        footer a:hover {
            color: #fff;
            text-decoration: underline;
        }

        @media (max-width: 700px) {
            header {
                padding: 0.85rem;
            }

            h1 {
                font-size: 1.15rem;
            }

            .subtitle {
                font-size: 0.78rem;
            }

            .hero-intro {
                font-size: 0.82rem;
            }

            .filters {
                overflow-x: auto;
                flex-wrap: nowrap;
                padding-bottom: 0.15rem;
            }

            .pagination {
                overflow-x: auto;
                flex-wrap: nowrap;
                padding-bottom: 0.15rem;
            }

            .status-panel {
                gap: 0.35rem;
                font-size: 0.75rem;
            }

            .status-item {
                padding: 0.32rem 0.5rem;
            }

            .status-toggle {
                display: inline-flex;
            }

            header.compact .status-panel {
                display: none;
            }

            body.show-status header.compact .status-panel {
                display: flex;
            }

            .latest-star-inner {
                /* minmax(0, …) : sinon la colonne s'élargit au nom de fichier et déborde. */
                grid-template-columns: minmax(0, 1fr);
            }

            .latest-star-title {
                font-size: 1.15rem;
            }
        }

        .species-section {
            padding: 1.5rem;
            max-width: 640px;
        }

        .species-section h2 {
            font-size: 1rem;
            font-weight: 700;
            margin: 0 0 1rem 0;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }

        .bar-row--species {
            display: block;
            margin-bottom: 0.75rem;
        }

        .bar-row--species .bar-label {
            font-size: 0.85rem;
            color: #ddd;
            margin-bottom: 0.3rem;
        }

        .bar-species-line {
            display: grid;
            grid-template-columns: 1fr 48px;
            gap: 0.5rem;
            align-items: center;
        }

        .bar-track {
            height: 18px;
            background: var(--panel2);
            border: 1px solid var(--border);
            border-radius: 999px;
            overflow: hidden;
            display: flex;
        }

        .bar-bird-fill {
            background: var(--bird);
            height: 100%;
        }

        .bar-bird-fill.probable {
            opacity: 0.4;
        }

        .bar-count {
            font-size: 0.82rem;
            color: var(--muted);
            text-align: right;
        }
    </style>
</head>
<body>

{% set sp_param = "&species=" ~ species_query if species_query else "" %}
{% macro species_line(image) %}
<div class="meta-species">
    {% if image.species %}
    <span title="{{ image.species }}">{{ image.species_french or image.species }}</span>
    <span class="certainty {{ '' if image.species_sure else 'probable' }}"
          title="Certitude {{ image.species_percent }} %"><span style="width: {{ image.species_percent }}%"></span></span>
    {% else %}
    <span class="unknown">Espèce non identifiée</span>
    {% endif %}
</div>
{% endmacro %}

<header id="page-header">
    <h1>{{ "Birdcam Admin" if admin_mode else "Mangeoire Cam" }}</h1>

    {% if not admin_mode %}
    <div class="public-info">
        <div class="public-info-stats">
            <span>{{ status.bird_count }} oiseaux</span>
            <span class="sep">·</span>
            <span>{{ status.star_count }} étoiles</span>
            <span class="sep">·</span>
            <span>{{ status.today_count }} aujourd'hui</span>
            <span class="sep">·</span>
            <span>{{ count }} affichées · page {{ page }}/{{ total_pages }}</span>
            <span class="sep">·</span>
            <span class="muted">{{ status.latest_date }}</span>
        </div>
        {% if status.top_species %}
        <div class="public-info-species">
            {% for sp in status.top_species %}
            <a href="/?filter=species&species={{ sp.name }}">{% if sp.french %}{{ sp.french }}{% else %}{{ sp.name }}{% endif %}</a><span class="sp-count">{{ sp.sure }}{% if sp.probable %}<span class="sp-probable" title="probables (confiance 0.3 à 0.6)"> +{{ sp.probable }} ?</span>{% endif %}</span>{% if not loop.last %}<span class="sep"> · </span>{% endif %}
            {% endfor %}
        </div>
        {% endif %}
    </div>
    {% endif %}

    <div class="hero-intro">
        A Raspberry Pi watches the feeder, captures movement, and keeps track of the winged visitors.
        Species identification is powered by a custom model trained on Paris garden birds — still learning, results will improve over time.
        <a href="https://toysfab.com/2026/05/une-camera-automatique-pour-mangeoire-a-oiseaux-avec-un-raspberry-pi/"
           target="_blank" rel="noopener noreferrer">Read the Toysfab build story</a>.
    </div>

    <div class="filters">
        <a class="filter {{ 'active' if mode == 'bird' else '' }}" href="/?filter=bird&per_page={{ per_page }}">Birds</a>
        <a class="filter {{ 'active' if mode == 'star' else '' }}" href="/?filter=star&per_page={{ per_page }}">Stars</a>
        <a class="filter {{ 'active' if mode == 'all' else '' }}" href="/?filter=all&per_page={{ per_page }}">All</a>
        <a class="filter {{ 'active' if mode == 'motion' else '' }}" href="/?filter=motion&per_page={{ per_page }}">Motion only</a>
        {% if mode == 'species' and species_query %}
        <a class="filter active" href="/?filter=bird&per_page={{ per_page }}">× {{ species_query }}</a>
        {% endif %}
        <a class="filter" href="/clips">Birds video</a>
        <a class="filter" href="/stats">Stats</a>
    </div>

    {% if admin_mode %}
    <button class="status-toggle" onclick="document.body.classList.toggle('show-status')">
        Status
    </button>

    <div class="status-panel">
        <div class="status-item">
            <span class="status-dot {{ 'ok' if status.birdcam_service.active else 'bad' }}"></span>
            Camera: {{ status.birdcam_service.status }}
        </div>

        {% if not status.clip_waiting %}
        <form method="post" action="/camera/toggle">
            <input type="hidden" name="filter" value="{{ mode }}">
            <input type="hidden" name="page" value="{{ page }}">
            <input type="hidden" name="per_page" value="{{ per_page }}">
            <button type="submit" class="camera-toggle-button {{ 'stop' if status.birdcam_service.active else 'start' }}">
                {{ "Stop Camera" if status.birdcam_service.active else "Start Camera" }}
            </button>
        </form>

        <form method="post" action="/camera/test">
            <input type="hidden" name="filter" value="{{ mode }}">
            <input type="hidden" name="page" value="{{ page }}">
            <input type="hidden" name="per_page" value="{{ per_page }}">
            <button type="submit" class="camera-toggle-button test">
                Test Camera
            </button>
        </form>
        {% endif %}

        {% if status.clip_waiting %}
        <div class="status-item">
            <span class="status-dot bad"></span>
            Clip : en attente d'un mouvement, aucune photo n'est prise
        </div>
        <form method="post" action="/clip/cancel">
            <button type="submit" class="camera-toggle-button stop">
                Annuler le clip
            </button>
        </form>
        {% elif status.birdcam_service.active %}
        <form method="post" action="/clip/request">
            <button type="submit" class="camera-toggle-button test">
                Faire une vidéo du prochain mouvement détecté
            </button>
        </form>
        {% endif %}

        {% if status.camera_test %}
        <div class="status-item">
            <span class="status-dot {{ 'ok' if status.camera_test.ok else 'bad' }}"></span>
            Test: {{ status.camera_test.message }} ({{ status.camera_test.timestamp }})
        </div>
        {% if status.camera_test.ok %}
        <div class="status-item">
            <a href="/camera-test-image?t={{ status.camera_test.timestamp }}" target="_blank">Voir la photo de test</a>
        </div>
        {% endif %}
        {% endif %}

        <div class="status-item">Birds: {{ status.bird_count }}</div>
        <div class="status-item">Stars: {{ status.star_count }}</div>
        <div class="status-item">Today: {{ status.today_count }}</div>
        <div class="status-item">Motion: {{ status.motion_count }}</div>
        {% if status.top_species %}
        <div class="status-item">
            Top : {% for sp in status.top_species %}<a href="/?filter=species&species={{ sp.name }}" style="color:inherit">{{ sp.name }}{% if sp.french %} ({{ sp.french }}){% endif %}</a> {{ sp.sure }}{% if sp.probable %} +{{ sp.probable }} ?{% endif %}{% if not loop.last %} · {% endif %}{% endfor %}
        </div>
        {% endif %}
        <div class="status-item">Latest: {{ status.latest_date }}</div>
        <div class="status-item">Disk: {{ status.free_gb }} GB free / {{ status.total_gb }} GB · {{ status.used_percent }}% used</div>
    </div>

    <div class="admin-warning">
        ADMIN MODE · Delete, retag and star actions are enabled.
    </div>
    {% endif %}
</header>

{% if latest_star and page == 1 and mode in ["bird", "star", "today", "all"] %}
<section class="latest-star">
    <a href="/view/{{ latest_star.name }}?filter=star">
        <div class="latest-star-inner">
            <img src="/thumb/{{ latest_star.name }}" alt="{{ latest_star.name }}">
            <div class="latest-star-text">
                <div class="latest-star-kicker">Latest star</div>
                <div class="latest-star-title">A favourite visitor from the feeder</div>
                <div class="latest-star-meta">
                    {{ species_line(latest_star) }}
                    <div class="meta-time">{{ latest_star.when }}</div>
                </div>
            </div>
        </div>
    </a>
</section>
{% endif %}

{% if images %}
<main class="gallery">
    {% for group in groups %}
    {% set burst = group.images|length > 1 %}
    {% if burst %}
    <section class="burst">
        <div class="burst-head">
            <strong>Rafale</strong> · {{ group.images|length }} photos · {{ group.images[0].when }}
            {% if admin_mode %}
            <label class="burst-select">
                <input type="checkbox" class="burst-cb"> Toute la rafale
            </label>
            {% endif %}
        </div>
        <div class="burst-cards">
    {% endif %}
    {% for image in group.images %}
    <div class="card" id="{{ image.name }}">
        <span class="badge {{ image.kind_class }}">{{ image.kind_label }}</span>
        {% if image.starred %}
        <span class="badge star">STAR</span>
        {% endif %}

        {% if admin_mode %}
        <label class="card-cb-wrap" onclick="event.stopPropagation()">
            <input type="checkbox" class="bulk-cb" value="{{ image.name }}">
        </label>
        {% endif %}

        <a href="/view/{{ image.name }}?filter={{ mode }}&per_page={{ per_page }}{{ sp_param }}">
            <img src="/thumb/{{ image.name }}" loading="lazy" alt="{{ image.species_french or image.species or image.kind_label }}">
        </a>

        <div class="meta">
            {{ species_line(image) }}
            <div class="meta-time">{{ image.when }}</div>
        </div>
    </div>
    {% endfor %}
    {% if burst %}
        </div>
    </section>
    {% endif %}
    {% endfor %}
</main>
{% else %}
<div class="empty">
    No pictures found for this filter in {{ capture_dir }}.
</div>
{% endif %}

<div class="bottom-nav">
    {% if admin_mode %}
    <button type="button" class="bk-btn bk-cancel" onclick="selectAll()">Select all</button>
    {% endif %}
    <div class="pagination">
        <a class="page-link {{ 'disabled' if page <= 1 else '' }}"
           href="/?filter={{ mode }}&page={{ page - 1 }}&per_page={{ per_page }}{{ sp_param }}">←</a>
        {% for p in page_numbers %}
            <a class="page-link {{ 'active' if p == page else '' }}"
               href="/?filter={{ mode }}&page={{ p }}&per_page={{ per_page }}{{ sp_param }}">{{ p }}</a>
        {% endfor %}
        <a class="page-link {{ 'disabled' if page >= total_pages else '' }}"
           href="/?filter={{ mode }}&page={{ page + 1 }}&per_page={{ per_page }}{{ sp_param }}">→</a>
    </div>
    <div class="per-page">
        <span class="muted">Par page :</span>
        {% for n in [12, 24, 48, 96] %}
            <a class="page-link {{ 'active' if n == per_page else '' }}"
               href="/?filter={{ mode }}&page=1&per_page={{ n }}{{ sp_param }}">{{ n }}</a>
        {% endfor %}
    </div>
</div>

{% if admin_mode and status.top_species %}
<div class="species-section">
    <h2>Espèces les plus fréquentes</h2>
    {% for sp in status.top_species %}
    <div class="bar-row--species">
        <div class="bar-label">
            <a href="/?filter=species&species={{ sp.name }}" style="color:inherit;text-decoration:none;border-bottom:1px dotted #666">
                {{ sp.name }}{% if sp.french %} <span style="opacity:.65">({{ sp.french }})</span>{% endif %}
            </a>
        </div>
        <div class="bar-species-line">
            <div class="bar-track">
                <div class="bar-bird-fill" style="width: {{ (sp.sure / status.top_species[0].count * 100) | round(1) }}%"></div>
                <div class="bar-bird-fill probable" style="width: {{ (sp.probable / status.top_species[0].count * 100) | round(1) }}%"></div>
            </div>
            <div class="bar-count">{{ sp.sure }}{% if sp.probable %} +{{ sp.probable }} ?{% endif %}</div>
        </div>
    </div>
    {% endfor %}
</div>
{% endif %}

<footer>
    Raspberry Pi Birdcam · {{ "admin" if admin_mode else "public" }} mode ·
    <a href="https://toysfab.com/2026/05/une-camera-automatique-pour-mangeoire-a-oiseaux-avec-un-raspberry-pi/"
       target="_blank"
       rel="noopener noreferrer">
        Toysfab article
    </a>
</footer>

{% if admin_mode %}
<div id="bulk-bar" class="bulk-bar" hidden>
    <span class="bulk-count" id="bulk-count"></span>
    <div class="bulk-btns">
        <button type="button" class="bk-btn bk-tag"     onclick="bulkSubmit('bird')">Bird</button>
        <button type="button" class="bk-btn bk-tag"     onclick="bulkSubmit('motion')">Motion</button>
        <button type="button" class="bk-btn bk-star"    onclick="bulkSubmit('star')">Star</button>
        <button type="button" class="bk-btn bk-del"     onclick="bulkSubmit('delete')">Delete</button>
        {% if paris_species %}
        <select id="bulk-species-select" class="bk-select">
            <option value="">— species —</option>
            {% for sp in paris_species %}
            <option value="{{ sp.scientific }}">{{ sp.french }}</option>
            {% endfor %}
        </select>
        <button type="button" class="bk-btn bk-species" onclick="bulkSubmit('correct_species')">Correct</button>
        {% endif %}
        <button type="button" class="bk-btn bk-species" onclick="bulkSubmit('clear_species')">Clear species</button>
        <button type="button" class="bk-btn bk-cancel"  onclick="clearSelection()">Cancel</button>
    </div>
    <form id="bulk-form" method="post" action="/bulk_action" style="display:none">
        <input type="hidden" name="filter" value="{{ mode }}">
        <input type="hidden" name="page" value="{{ page }}">
        <input type="hidden" name="per_page" value="{{ per_page }}">
        <input type="hidden" name="action" id="bulk-action-val">
        <input type="hidden" name="species" id="bulk-species-val">
    </form>
</div>
{% endif %}

<script>
    const header = document.getElementById("page-header");
    let isCompact = false;

    function updateHeaderCompactMode() {
        if (!header) return;
        const y = window.scrollY;
        if (!isCompact && y > 80) {
            isCompact = true;
            header.classList.add("compact");
        } else if (isCompact && y < 50) {
            isCompact = false;
            header.classList.remove("compact");
            document.body.classList.remove("show-status");
        }
    }

    window.addEventListener("scroll", updateHeaderCompactMode, { passive: true });
    updateHeaderCompactMode();


    // ── Sélection groupée ──────────────────────────────────────────────────
    const bulkBar   = document.getElementById("bulk-bar");
    const bulkCount = document.getElementById("bulk-count");
    const bulkForm  = document.getElementById("bulk-form");

    function getChecked() {
        return [...document.querySelectorAll(".bulk-cb:checked")];
    }

    function updateBulkBar() {
        if (!bulkBar) return;
        const n = getChecked().length;
        bulkBar.hidden = n === 0;
        if (n > 0) bulkCount.textContent = n + " sélectionnée" + (n > 1 ? "s" : "");
    }

    function bulkSubmit(action) {
        const checked = getChecked();
        if (checked.length === 0) return;
        if (action === "correct_species") {
            const sel = document.getElementById("bulk-species-select");
            if (!sel || !sel.value) { alert("Select a species first."); return; }
            document.getElementById("bulk-species-val").value = sel.value;
        }
        if (action === "delete" && !confirm("Delete " + checked.length + " photo(s)?")) return;
        document.getElementById("bulk-action-val").value = action;
        bulkForm.querySelectorAll(".bf").forEach(el => el.remove());
        checked.forEach(cb => {
            const inp = document.createElement("input");
            inp.type = "hidden"; inp.name = "filenames";
            inp.value = cb.value; inp.className = "bf";
            bulkForm.appendChild(inp);
        });
        bulkForm.submit();
    }

    function selectAll() {
        document.querySelectorAll(".burst-cb").forEach(cb => { cb.checked = true; });
        document.querySelectorAll(".bulk-cb").forEach(cb => {
            cb.checked = true;
            cb.closest(".card").classList.add("selected");
        });
        updateBulkBar();
    }

    function clearSelection() {
        document.querySelectorAll(".burst-cb").forEach(cb => { cb.checked = false; });
        document.querySelectorAll(".bulk-cb").forEach(cb => {
            cb.checked = false;
            cb.closest(".card").classList.remove("selected");
        });
        updateBulkBar();
    }

    document.querySelectorAll(".bulk-cb").forEach(cb => {
        cb.addEventListener("change", function () {
            this.closest(".card").classList.toggle("selected", this.checked);
            const burst = this.closest(".burst");
            if (burst) {
                const all = [...burst.querySelectorAll(".bulk-cb")];
                burst.querySelector(".burst-cb").checked = all.every(c => c.checked);
            }
            updateBulkBar();
        });
    });

    // Case "Toute la rafale" : coche ou décoche toutes les photos du cadre.
    document.querySelectorAll(".burst-cb").forEach(burstCb => {
        burstCb.addEventListener("change", function () {
            this.closest(".burst").querySelectorAll(".bulk-cb").forEach(cb => {
                cb.checked = this.checked;
                cb.closest(".card").classList.toggle("selected", this.checked);
            });
            updateBulkBar();
        });
    });
</script>

</body>
</html>
"""


VIEW_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{{ image.species_french or image.species or image.kind_label }} · {{ image.date }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    {# Le Pi sert lentement les photos en pleine taille : on charge la suivante d'avance. #}
    {% if next_name %}<link rel="prefetch" href="/image/{{ next_name }}">{% endif %}
    <style>
        :root {
            --bg: #0d1110;
            --panel: #171d1b;
            --border: #34413b;
            --text: #f2f1e8;
            --muted: #a9b3ad;
            --bird: #5fd38d;
            --motion: #f0b35a;
            --danger: #e46d5d;
            --blue: #70a7d8;
        }
        * { box-sizing: border-box; }
        html, body { margin: 0; height: 100%; }
        body {
            background: var(--bg);
            color: var(--text);
            font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
            display: flex;
            flex-direction: column;
        }
        a { color: inherit; }
        .topbar {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 16px;
            background: var(--panel);
            border-bottom: 1px solid var(--border);
            flex-wrap: wrap;
        }
        .back {
            text-decoration: none;
            font-weight: 600;
            padding: 6px 12px;
            border: 1px solid var(--border);
            border-radius: 8px;
        }
        .info { flex: 1; min-width: 0; font-size: 14px; color: var(--muted); }
        .info strong { color: var(--text); }
        .position { font-size: 14px; color: var(--muted); white-space: nowrap; }
        .stage {
            flex: 1;
            min-height: 0;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 8px;
        }
        .stage img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
            border-radius: 6px;
        }
        .nav {
            position: absolute;
            top: 50%;
            transform: translateY(-50%);
            width: 52px;
            height: 72px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 32px;
            text-decoration: none;
            background: rgba(13, 17, 16, .65);
            border: 1px solid var(--border);
            border-radius: 10px;
        }
        .nav.prev { left: 12px; }
        .nav.next { right: 12px; }
        .nav.disabled { opacity: .25; pointer-events: none; }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 700;
            color: #0d1110;
            margin-right: 4px;
        }
        .badge.bird { background: var(--bird); }
        .badge.motion { background: var(--motion); }
        .badge.star { background: #ffd35a; }
        .certainty {
            display: inline-block;
            vertical-align: middle;
            width: 48px;
            height: 6px;
            border-radius: 999px;
            background: rgba(255, 255, 255, .12);
            overflow: hidden;
        }
        .certainty > span { display: block; height: 100%; background: var(--bird); }
        .certainty.probable > span { background: var(--motion); }
        .actions {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            align-items: center;
            justify-content: center;
            padding: 10px 16px;
            background: var(--panel);
            border-top: 1px solid var(--border);
        }
        .actions form { margin: 0; display: flex; gap: 6px; align-items: center; }
        .actions button, .actions select {
            font: inherit;
            font-size: 14px;
            padding: 7px 12px;
            border-radius: 8px;
            border: 1px solid var(--border);
            background: #222b27;
            color: var(--text);
            cursor: pointer;
        }
        .actions button.danger { border-color: var(--danger); color: var(--danger); }
    </style>
</head>
<body>
{% set nav_query = "filter=" ~ mode ~ "&per_page=" ~ per_page ~ ("&species=" ~ species_query|urlencode if species_query else "") %}
<div class="topbar">
    <a class="back" href="{{ gallery_url }}">← Galerie</a>
    <div class="info">
        <span class="badge {{ image.kind_class }}">{{ image.kind_label }}</span>
        {% if image.starred %}<span class="badge star">STAR</span>{% endif %}
        {% if image.species %}
        <strong title="{{ image.species }}">{{ image.species_french or image.species }}</strong>
        <span class="certainty {{ '' if image.species_sure else 'probable' }}"
              title="Certitude {{ image.species_percent }} %"><span style="width: {{ image.species_percent }}%"></span></span>
        {% endif %}
        · {{ image.when }}
        · <a href="/image/{{ image.name }}">original</a>
    </div>
    {% if position %}<div class="position">{{ position }} / {{ total }}</div>{% endif %}
</div>

<div class="stage">
    <img src="/image/{{ image.name }}" alt="{{ image.name }}">
    <a class="nav prev {{ '' if prev_name else 'disabled' }}" id="prev"
       href="{{ '/view/' ~ prev_name ~ '?' ~ nav_query if prev_name else '#' }}" title="Précédente (←)">‹</a>
    <a class="nav next {{ '' if next_name else 'disabled' }}" id="next"
       href="{{ '/view/' ~ next_name ~ '?' ~ nav_query if next_name else '#' }}" title="Suivante (→)">›</a>
</div>

{% if admin_mode %}
<div class="actions">
    {% macro action(route, label, extra="", cls="", confirm_text="") %}
    <form method="post" action="/{{ route }}/{{ image.name }}"
          {% if confirm_text %}onsubmit="return confirm('{{ confirm_text }}')"{% endif %}>
        <input type="hidden" name="view" value="1">
        <input type="hidden" name="filter" value="{{ mode }}">
        <input type="hidden" name="species_filter" value="{{ species_query }}">
        <input type="hidden" name="per_page" value="{{ per_page }}">
        {{ extra | safe }}
        <button type="submit" class="{{ cls }}">{{ label }}</button>
    </form>
    {% endmacro %}
    {% if image.kind != "bird" %}{{ action("retag", "Bird", '<input type="hidden" name="new_tag" value="bird">') }}{% endif %}
    {% if image.kind != "motion" %}{{ action("retag", "Motion", '<input type="hidden" name="new_tag" value="motion">') }}{% endif %}
    {{ action("star", "Unstar" if image.starred else "Star") }}
    {% if paris_species %}
    <form method="post" action="/correct_species/{{ image.name }}">
        <input type="hidden" name="view" value="1">
        <input type="hidden" name="filter" value="{{ mode }}">
        <input type="hidden" name="species_filter" value="{{ species_query }}">
        <input type="hidden" name="per_page" value="{{ per_page }}">
        <select name="species" required>
            <option value="">— species —</option>
            {% for sp in paris_species %}
            <option value="{{ sp.scientific }}" {{ 'selected' if image.species and sp.scientific.lower() == image.species.lower() else '' }}>{{ sp.french }}</option>
            {% endfor %}
        </select>
        <button type="submit">Correct</button>
    </form>
    {% endif %}
    {% if image.species %}{{ action("clear_species", "Clear species") }}{% endif %}
    {{ action("delete", "Delete", cls="danger", confirm_text="Delete this photo?") }}
</div>
{% endif %}

<script>
    const prev = document.getElementById("prev");
    const next = document.getElementById("next");
    const go = link => { if (!link.classList.contains("disabled")) location.href = link.href; };

    document.addEventListener("keydown", event => {
        if (event.target.closest("select, input, textarea")) return;
        if (event.altKey || event.metaKey || event.ctrlKey || event.shiftKey) return;
        if (event.key === "ArrowLeft") go(prev);
        else if (event.key === "ArrowRight") go(next);
        else if (event.key === "Escape") location.href = {{ gallery_url|tojson }};
    });

    // Glissement horizontal sur mobile.
    let startX = null, startY = null;
    const stage = document.querySelector(".stage");
    const zoomed = () => window.visualViewport && window.visualViewport.scale > 1.01;
    stage.addEventListener("touchstart", e => {
        // Zoom à deux doigts ou déplacement d'une image zoomée : pas de changement de photo.
        if (e.touches.length !== 1 || zoomed()) { startX = null; return; }
        startX = e.touches[0].clientX; startY = e.touches[0].clientY;
    }, { passive: true });
    stage.addEventListener("touchmove", e => {
        if (e.touches.length !== 1) startX = null;
    }, { passive: true });
    stage.addEventListener("touchend", e => {
        if (startX === null || zoomed()) return;
        const dx = e.changedTouches[0].clientX - startX;
        const dy = e.changedTouches[0].clientY - startY;
        startX = null;
        if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) go(dx > 0 ? prev : next);
    });
</script>
</body>
</html>
"""


CLIPS_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{{ "Birdcam Admin" if admin_mode else "Mangeoire Cam" }} · Birds video</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root {
            --bg: #0d1110;
            --panel: #171d1b;
            --border: #34413b;
            --text: #f2f1e8;
            --muted: #a9b3ad;
            --bird: #5fd38d;
            --danger: #e46d5d;
        }
        body {
            margin: 0;
            padding: 1rem;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: var(--bg);
            color: var(--text);
        }
        a { color: var(--bird); }
        h1 { font-size: 1.3rem; margin: 0 0 0.5rem; }
        .notice { color: var(--muted); margin: 0.5rem 0 1rem; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(min(100%, 22rem), 1fr));
            gap: 1rem;
        }
        .clip {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 0.6rem;
        }
        .clip video { width: 100%; border-radius: 8px; background: #000; }
        .clip-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 0.4rem;
            font-size: 0.85rem;
            color: var(--muted);
        }
        .clip button {
            background: var(--danger);
            color: #111;
            border: none;
            border-radius: 999px;
            padding: 0.3rem 0.7rem;
            font-weight: 700;
            cursor: pointer;
        }
    </style>
</head>
<body>
    <h1>Birds video</h1>
    <a href="/">← Galerie</a>
    {% if waiting %}
    <p class="notice">Un clip est en attente du prochain mouvement. Aucune photo n'est prise pendant ce temps.</p>
    {% endif %}
    {% if not clips %}
    <p class="notice">Aucun clip pour le moment.</p>
    {% endif %}
    <div class="grid">
        {% for clip in clips %}
        <div class="clip">
            <video controls preload="metadata" src="/clip/{{ clip.name }}"></video>
            <div class="clip-meta">
                <span>{{ clip.date }} · {{ clip.size_mb }} Mo</span>
                {% if admin_mode %}
                <form method="post" action="/clip/delete/{{ clip.name }}">
                    <button type="submit">Supprimer</button>
                </form>
                {% endif %}
            </div>
        </div>
        {% endfor %}
    </div>
</body>
</html>
"""


STATS_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Birdcam Stats</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <style>
        :root {
            --bg: #0d1110;
            --panel: #171d1b;
            --panel2: #222b27;
            --border: #34413b;
            --text: #f2f1e8;
            --muted: #a9b3ad;
            --bird: #5fd38d;
            --motion: #f0b35a;
            --unknown: #777;
            --toysfab: #ffcf70;
        }

        body {
            margin: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background:
                radial-gradient(circle at top left, rgba(95, 211, 141, 0.12), transparent 34rem),
                radial-gradient(circle at top right, rgba(240, 179, 90, 0.10), transparent 30rem),
                var(--bg);
            color: var(--text);
        }

        header {
            padding: 1.2rem;
            background: rgba(23, 29, 27, 0.96);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 10;
            backdrop-filter: blur(8px);
        }

        h1 {
            margin: 0;
            font-size: 1.4rem;
        }

        h2 {
            margin: 2rem 0 0.4rem;
            font-size: 1.2rem;
        }

        .subtitle {
            margin-top: 0.35rem;
            color: var(--muted);
            font-size: 0.9rem;
            line-height: 1.45;
        }

        .tabs {
            margin-top: 0.9rem;
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }

        .tab {
            color: var(--text);
            background: var(--panel2);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.45rem 0.75rem;
            text-decoration: none;
            font-size: 0.85rem;
        }

        .tab.active {
            background: #f4e7c5;
            color: #111;
            border-color: #f4e7c5;
        }

        main {
            padding: 1rem;
            max-width: 1100px;
            margin: 0 auto;
        }

        .editorial-note {
            background:
                linear-gradient(135deg, rgba(255, 207, 112, 0.14), rgba(95, 211, 141, 0.08)),
                var(--panel);
            border: 1px solid rgba(255, 207, 112, 0.35);
            border-radius: 14px;
            padding: 1rem;
            color: #dce3de;
            line-height: 1.5;
            margin-top: 1rem;
        }

        .summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 0.8rem;
            margin-top: 1rem;
        }

        .summary-card {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1rem;
        }

        .summary-number {
            font-size: 1.8rem;
            font-weight: 700;
        }

        .summary-label {
            color: var(--muted);
            font-size: 0.85rem;
            margin-top: 0.2rem;
        }

        .chart {
            display: grid;
            gap: 0.55rem;
            margin-top: 1rem;
        }

        .bar-row {
            display: grid;
            grid-template-columns: 90px 1fr 90px;
            gap: 0.75rem;
            align-items: center;
            font-size: 0.85rem;
        }

        .bar-label {
            color: #ddd;
            white-space: nowrap;
        }

        .bar-track {
            height: 24px;
            background: var(--panel2);
            border: 1px solid var(--border);
            border-radius: 999px;
            overflow: hidden;
            display: flex;
        }

        .bar-bird {
            background: var(--bird);
            height: 100%;
        }

        .bar-bird.probable {
            opacity: 0.4;
        }

        .bar-motion {
            background: var(--motion);
            height: 100%;
        }

        .bar-unknown {
            background: var(--unknown);
            height: 100%;
        }

        .bar-value {
            color: var(--muted);
            text-align: right;
            white-space: nowrap;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
        }

        th, td {
            padding: 0.65rem;
            border-bottom: 1px solid var(--border);
            text-align: right;
            font-size: 0.85rem;
        }

        th:first-child,
        td:first-child {
            text-align: left;
        }

        th {
            color: #fff;
            background: var(--panel2);
        }

        td {
            color: #ddd;
        }

        tr:last-child td {
            border-bottom: none;
        }

        footer {
            padding: 1rem;
            color: #777;
            font-size: 0.8rem;
            text-align: center;
        }

        .bar-row--species {
            display: block;
            margin-bottom: 0.75rem;
        }

        .bar-row--species .bar-label {
            white-space: normal;
            margin-bottom: 0.3rem;
            font-size: 0.85rem;
            color: #ddd;
        }

        .bar-row--species .bar-species-line {
            display: grid;
            grid-template-columns: 1fr 48px;
            gap: 0.5rem;
            align-items: center;
        }

        .bar-row--species .bar-value {
            text-align: right;
            font-size: 0.85rem;
        }

        @media (max-width: 700px) {
            .bar-row {
                grid-template-columns: 64px 1fr;
            }

            .bar-value {
                grid-column: 2;
                text-align: left;
            }
        }
    </style>
</head>
<body>

<header>
    <h1>When do the birds visit?</h1>
    <div class="subtitle">
        A small statistical notebook from the feeder. The charts separate confirmed birds from raw motion captures.
    </div>

    <div class="tabs">
        <a class="tab" href="/">Gallery</a>
        <a class="tab active" href="/stats">Stats</a>
    </div>
</header>

<main>
    <section class="editorial-note">
        {{ stats.editorial_summary }}
    </section>

    <section class="summary">
        <div class="summary-card">
            <div class="summary-number">{{ stats.total }}</div>
            <div class="summary-label">Total pictures</div>
        </div>

        <div class="summary-card">
            <div class="summary-number">{{ stats.total_bird }}</div>
            <div class="summary-label">Bird pictures</div>
        </div>

        <div class="summary-card">
            <div class="summary-number">{{ stats.total_star }}</div>
            <div class="summary-label">Starred pictures</div>
        </div>

        <div class="summary-card">
            <div class="summary-number">{{ stats.today_bird }}</div>
            <div class="summary-label">Bird pictures today</div>
        </div>
    </section>

    <h2>Most active hours</h2>
    <div class="subtitle">
        This shows when the feeder is most often visited or triggered during the day.
    </div>

    <section class="chart">
        {% for row in stats.hourly_rows %}
        <div class="bar-row">
            <div class="bar-label">{{ row.hour }}</div>

            <div class="bar-track">
                {% if row.total > 0 %}
                    <div class="bar-bird"
                         style="width: {{ (row.bird / stats.max_hourly_total * 100) | round(1) }}%">
                    </div>
                    <div class="bar-motion"
                         style="width: {{ (row.motion / stats.max_hourly_total * 100) | round(1) }}%">
                    </div>
                {% endif %}
            </div>

            <div class="bar-value">
                {{ row.total }} total · {{ row.bird }} bird
            </div>
        </div>
        {% endfor %}
    </section>

    <h2>Daily rhythm</h2>
    <div class="subtitle">
        A day-by-day view of the feeder activity.
    </div>

    <section class="chart">
        {% for row in stats.daily_rows %}
        <div class="bar-row">
            <div class="bar-label">{{ row.day }}</div>

            <div class="bar-track">
                {% if row.total > 0 %}
                    <div class="bar-bird"
                         style="width: {{ (row.bird / stats.max_daily_total * 100) | round(1) }}%">
                    </div>
                    <div class="bar-motion"
                         style="width: {{ (row.motion / stats.max_daily_total * 100) | round(1) }}%">
                    </div>
                    <div class="bar-unknown"
                         style="width: {{ (row.unknown / stats.max_daily_total * 100) | round(1) }}%">
                    </div>
                {% endif %}
            </div>

            <div class="bar-value">
                {{ row.total }} total · {{ row.bird }} bird
            </div>
        </div>
        {% endfor %}
    </section>

    {% if stats.top_species %}
    <h2>Most identified species</h2>
    <div class="subtitle">
        Based on AI classification of bird pictures (iNaturalist model). Faded bars and "+N ?" are probable identifications (confidence 0.3 to 0.6).
    </div>

    <section class="chart">
        {% for sp in stats.top_species %}
        <div class="bar-row--species">
            <div class="bar-label">
                <a href="/?filter=species&species={{ sp.name }}" style="color:inherit;text-decoration:none;border-bottom:1px dotted #666">
                    {{ sp.name }}{% if sp.french %} <span style="opacity:.65">({{ sp.french }})</span>{% endif %}
                </a>
            </div>
            <div class="bar-species-line">
                <div class="bar-track">
                    <div class="bar-bird" style="width: {{ (sp.sure / stats.max_species_count * 100) | round(1) }}%"></div>
                    <div class="bar-bird probable" style="width: {{ (sp.probable / stats.max_species_count * 100) | round(1) }}%"></div>
                </div>
                <div class="bar-value">{{ sp.sure }}{% if sp.probable %} +{{ sp.probable }} ?{% endif %}</div>
            </div>
        </div>
        {% endfor %}
    </section>
    {% endif %}

    <h2>Daily table</h2>

    <table>
        <thead>
            <tr>
                <th>Day</th>
                <th>Bird</th>
                <th>Stars</th>
                <th>Motion</th>
                <th>Unknown</th>
                <th>Total</th>
            </tr>
        </thead>
        <tbody>
            {% for row in stats.daily_rows %}
            <tr>
                <td>{{ row.day }}</td>
                <td>{{ row.bird }}</td>
                <td>{{ row.star }}</td>
                <td>{{ row.motion }}</td>
                <td>{{ row.unknown }}</td>
                <td>{{ row.total }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</main>

<footer>
    Raspberry Pi Birdcam
</footer>

</body>
</html>
"""


def is_starred_filename(name: str) -> bool:
    return name.startswith("star_")


def strip_star_prefix(name: str) -> str:
    if name.startswith("star_"):
        return name[len("star_"):]
    return name


def base_kind_from_name(name: str) -> str:
    clean = strip_star_prefix(name)

    if clean.startswith("bird_"):
        return "bird"

    if clean.startswith("motion_"):
        return "motion"

    return "unknown"


def parse_image_metadata(path: Path):
    name = path.name
    starred = is_starred_filename(name)
    clean_name = strip_star_prefix(name)
    kind = base_kind_from_name(name)

    if kind == "bird":
        kind_label = "BIRD"
        kind_class = "bird"
    elif kind == "motion":
        kind_label = "MOTION"
        kind_class = "motion"
    else:
        kind_label = "PHOTO"
        kind_class = "motion"

    confidence_match = re.search(r"_conf([0-9.]+)", clean_name)
    # Arrête avant _sp pour ne pas capturer le suffixe espèce.
    best_match = re.search(r"_best([a-zA-Z0-9_-]+?)(?=_sp[a-z]|\.jpg|$)", clean_name)
    motion_match = re.search(r"_motion([0-9]+)", clean_name)
    species_match = re.search(r"_sp([a-zA-Z0-9_-]+?)_spconf([0-9]+(?:\.[0-9]+)?)", clean_name)

    confidence = confidence_match.group(1) if confidence_match else "n/a"
    best_label = best_match.group(1) if best_match else "n/a"
    motion_score = motion_match.group(1) if motion_match else "n/a"
    species = species_match.group(1).replace("_", " ").title() if species_match else None
    species_conf = species_match.group(2) if species_match else None
    species_sure = bool(species_conf) and float(species_conf) >= SPECIES_SURE_THRESHOLD

    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime)

    return {
        "name": name,
        "clean_name": clean_name,
        "kind": kind,
        "kind_label": kind_label,
        "kind_class": kind_class,
        "starred": starred,
        "confidence": confidence,
        "best_label": best_label,
        "motion_score": motion_score,
        "species": species,
        "species_conf": species_conf,
        "species_sure": species_sure,
        "species_french": french_name(species) if species else "",
        "species_percent": round(float(species_conf) * 100) if species_conf else 0,
        "when": modified.strftime("%d/%m/%Y %H:%M:%S"),
        "date": modified.strftime("%Y-%m-%d %H:%M:%S"),
        "day": modified.strftime("%Y-%m-%d"),
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


def filter_images(images, mode: str, species_query: str = ""):
    today_key = date.today().strftime("%Y-%m-%d")

    if mode == "bird":
        return [image for image in images if image["kind"] == "bird"]

    if mode == "star":
        return [image for image in images if image["starred"]]

    if mode == "today":
        return [image for image in images if image["day"] == today_key and image["kind"] == "bird"]

    if mode == "motion":
        return [image for image in images if image["kind"] == "motion"]

    if mode == "species" and species_query:
        q = species_query.lower()
        return [
            image for image in images
            if image["kind"] == "bird" and (image.get("species") or "").lower() == q
        ]

    return images


BURST_NAME_RE = re.compile(r"_(\d{8})_(\d{2})(\d{2})(\d{2})_(\d{3})_burst(\d+)_motion(\d+)")
BURST_MAX_GAP_MS = 3000


def burst_info(image):
    """
    (instant de prise en ms, index dans la rafale, score de mouvement) lus
    dans le nom de fichier, ou None. Arithmétique entière plutôt que
    datetime.strptime : moins coûteux sur le Pi 3B, et un nom à date
    impossible ne fait jamais tomber la galerie. L'instant n'est exact qu'au
    sein d'une même journée, ce qui suffit pour trier et pour l'écart de 3 s.
    """
    match = BURST_NAME_RE.search(image["clean_name"])
    if not match:
        return None
    day, hours, minutes, seconds, millis, index, motion = match.groups()
    taken = (
        int(day) * 86_400_000 + int(hours) * 3_600_000
        + int(minutes) * 60_000 + int(seconds) * 1000 + int(millis)
    )
    return taken, int(index), motion


def group_bursts(images):
    """
    Regroupe les photos d'une même rafale : même score de mouvement, moins de
    BURST_MAX_GAP_MS entre deux photos, index de rafale strictement croissant
    (un retour à burst0 ouvre une nouvelle rafale, même au même score).
    Rend les rafales de la plus récente à la plus ancienne, et les photos
    d'une rafale dans l'ordre de prise, même si leurs mtime sont égales
    (copie ou restauration qui arrondit les dates).
    """
    infos = {image["name"]: burst_info(image) for image in images}
    ordered = sorted(
        images,
        key=lambda image: (int(image["mtime"]), infos[image["name"]] or (0, 0, ""), image["name"]),
        reverse=True,
    )

    groups = []
    for image in ordered:
        info = infos[image["name"]]
        last = groups[-1] if groups else None
        last_info = infos[last[-1]["name"]] if last else None
        if (
            info and last_info
            and info[2] == last_info[2]
            and info[1] < last_info[1]
            and last_info[0] - info[0] <= BURST_MAX_GAP_MS
        ):
            last.append(image)
        else:
            groups.append([image])

    return [
        {"images": sorted(group, key=lambda image: infos[image["name"]] or (0, 0, ""))}
        for group in groups
    ]


def split_pages(groups, per_page: int):
    """Pages d'au moins per_page photos, sans jamais couper une rafale."""
    pages = [[]]
    count = 0
    for group in groups:
        if count >= per_page:
            pages.append([])
            count = 0
        pages[-1].append(group)
        count += len(group["images"])
    return pages


def ordered_images(groups):
    """Photos dans l'ordre d'affichage de la galerie (pour la visionneuse)."""
    return [image for group in groups for image in group["images"]]


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


def read_camera_test_status():
    if not CAMERA_TEST_STATUS_PATH.exists():
        return None
    try:
        return json.loads(CAMERA_TEST_STATUS_PATH.read_text())
    except Exception:
        return None


def run_camera_test():
    """
    Arrête brièvement birdcam.service, prend une photo avec rpicam-still
    pour vérifier que la caméra répond encore, puis relance le service.
    Un seul processus peut tenir le capteur CSI ouvert à la fois, d'où
    l'arrêt temporaire.
    """
    require_admin()

    was_active = service_status("birdcam")["active"]

    if was_active:
        subprocess.run(["sudo", "systemctl", "stop", "birdcam"], capture_output=True, timeout=10)
        time.sleep(1)

    result = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "ok": False,
        "message": "",
    }

    try:
        proc = subprocess.run(
            ["rpicam-still", "-t", "2000", "-o", str(CAMERA_TEST_IMAGE_PATH)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0 and CAMERA_TEST_IMAGE_PATH.exists():
            result["ok"] = True
            result["message"] = "Caméra OK"
        else:
            result["message"] = (proc.stderr or proc.stdout or "échec rpicam-still").strip()[-500:]
    except subprocess.TimeoutExpired:
        result["message"] = "rpicam-still n'a pas répondu (timeout)"
    except Exception as error:
        result["message"] = str(error)

    if was_active:
        # Type=notify : "start" attend READY=1 (~11 s après chargement des modèles).
        subprocess.run(["sudo", "systemctl", "start", "birdcam"], capture_output=True, timeout=30)

    CAMERA_TEST_STATUS_PATH.write_text(json.dumps(result))
    return result


def build_status(all_images):
    if all_images:
        latest = all_images[0]
        latest_name = latest["name"]
        latest_date = latest["date"]
    else:
        latest_name = "none"
        latest_date = "n/a"

    disk = shutil.disk_usage(CAPTURE_DIR if CAPTURE_DIR.exists() else Path.home())
    today_key = date.today().strftime("%Y-%m-%d")

    free_gb = disk.free / (1024 ** 3)
    total_gb = disk.total / (1024 ** 3)
    used_percent = (disk.used / disk.total) * 100

    # Top espèces : compter les species uniques sur les photos bird_
    top_species = rank_species(all_images, 5)

    return {
        "birdcam_service": service_status("birdcam"),
        "clip_waiting": service_status(CLIP_SERVICE)["active"],
        "camera_test": read_camera_test_status(),
        "bird_count": sum(1 for image in all_images if image["kind"] == "bird"),
        "motion_count": sum(1 for image in all_images if image["kind"] == "motion"),
        "star_count": sum(1 for image in all_images if image["starred"]),
        "today_count": sum(1 for image in all_images if image["day"] == today_key and image["kind"] == "bird"),
        "latest_name": latest_name,
        "latest_date": latest_date,
        "free_gb": f"{free_gb:.1f}",
        "total_gb": f"{total_gb:.1f}",
        "used_percent": f"{used_percent:.0f}",
        "top_species": top_species,
    }


def build_stats(all_images):
    daily = {}
    hourly = {hour: {"bird": 0, "motion": 0, "total": 0} for hour in range(24)}

    total_bird = 0
    total_motion = 0
    total_unknown = 0
    total_star = 0
    today_bird = 0
    today_key = date.today().strftime("%Y-%m-%d")

    for image in all_images:
        dt = datetime.fromtimestamp(image["mtime"])
        day_key = dt.strftime("%Y-%m-%d")
        hour_key = dt.hour

        kind = image["kind"]

        if day_key not in daily:
            daily[day_key] = {
                "bird": 0,
                "motion": 0,
                "unknown": 0,
                "star": 0,
                "total": 0,
            }

        if image["starred"]:
            daily[day_key]["star"] += 1
            total_star += 1

        if kind == "bird":
            daily[day_key]["bird"] += 1
            hourly[hour_key]["bird"] += 1
            total_bird += 1
            if day_key == today_key:
                today_bird += 1
        elif kind == "motion":
            daily[day_key]["motion"] += 1
            hourly[hour_key]["motion"] += 1
            total_motion += 1
        else:
            daily[day_key]["unknown"] += 1
            total_unknown += 1

        daily[day_key]["total"] += 1
        hourly[hour_key]["total"] += 1

    daily_rows = []

    for day in sorted(daily.keys(), reverse=True):
        row = daily[day]
        daily_rows.append({
            "day": day,
            "bird": row["bird"],
            "motion": row["motion"],
            "unknown": row["unknown"],
            "star": row["star"],
            "total": row["total"],
        })

    hourly_rows = []

    for hour in range(24):
        row = hourly[hour]
        hourly_rows.append({
            "hour": f"{hour:02d}:00",
            "bird": row["bird"],
            "motion": row["motion"],
            "total": row["total"],
        })

    max_daily_total = max([row["total"] for row in daily_rows], default=1)
    max_hourly_total = max([row["total"] for row in hourly_rows], default=1)

    best_hour = max(hourly_rows, key=lambda row: row["bird"], default=None)
    best_day = max(daily_rows, key=lambda row: row["bird"], default=None)

    if best_hour and best_hour["bird"] > 0:
        hour_sentence = f"The most active bird hour is around {best_hour['hour']} with {best_hour['bird']} bird picture(s)."
    else:
        hour_sentence = "No clear bird activity pattern has emerged yet."

    if best_day and best_day["bird"] > 0:
        day_sentence = f"The strongest bird day so far is {best_day['day']} with {best_day['bird']} bird picture(s)."
    else:
        day_sentence = "The daily rhythm is still waiting for more bird visits."

    editorial_summary = f"{hour_sentence} {day_sentence} Today, the feeder has produced {today_bird} bird picture(s)."

    top_species = rank_species(all_images, 10)
    max_species_count = top_species[0]["count"] if top_species else 1

    return {
        "daily_rows": daily_rows,
        "hourly_rows": hourly_rows,
        "max_daily_total": max_daily_total,
        "max_hourly_total": max_hourly_total,
        "total_bird": total_bird,
        "total_motion": total_motion,
        "total_unknown": total_unknown,
        "total_star": total_star,
        "today_bird": today_bird,
        "total": total_bird + total_motion + total_unknown,
        "editorial_summary": editorial_summary,
        "top_species": top_species,
        "max_species_count": max_species_count,
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


def require_admin():
    if not ADMIN_MODE:
        abort(403)


def thumb_path_for(filename: str):
    safe_name = filename.replace("/", "_")
    return THUMB_DIR / safe_name


def delete_thumbnail(filename: str):
    thumb = thumb_path_for(filename)
    if thumb.exists():
        thumb.unlink()


def delete_image_and_thumbnail(filename: str):
    require_admin()

    image_path = safe_image_path(filename)
    delete_thumbnail(filename)

    if image_path.exists():
        image_path.unlink()


def make_unique_path(path: Path):
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    counter = 1

    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def retag_image(filename: str, new_tag: str):
    require_admin()

    if new_tag not in {"bird", "motion"}:
        abort(400)

    image_path = safe_image_path(filename)
    old_name = image_path.name
    starred = is_starred_filename(old_name)

    clean_name = strip_star_prefix(old_name)

    if clean_name.startswith("bird_"):
        rest = clean_name[len("bird_"):]
    elif clean_name.startswith("motion_"):
        rest = clean_name[len("motion_"):]
    else:
        rest = clean_name

    new_name = f"{new_tag}_{rest}"

    if starred:
        new_name = f"star_{new_name}"

    new_path = make_unique_path(CAPTURE_DIR / new_name)

    delete_thumbnail(old_name)
    image_path.rename(new_path)
    delete_thumbnail(new_path.name)

    return new_path.name


def toggle_star_image(filename: str):
    require_admin()

    image_path = safe_image_path(filename)
    old_name = image_path.name

    if is_starred_filename(old_name):
        new_name = strip_star_prefix(old_name)
    else:
        new_name = f"star_{old_name}"

    new_path = make_unique_path(CAPTURE_DIR / new_name)

    delete_thumbnail(old_name)
    image_path.rename(new_path)
    delete_thumbnail(new_path.name)

    return new_path.name


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


def current_nav_args_from_form():
    mode = request.form.get("filter", "bird")
    page = request.form.get("page", "1")
    per_page = request.form.get("per_page", str(DEFAULT_PER_PAGE))

    if mode not in {"all", "bird", "motion", "star", "today"}:
        mode = "bird"

    return mode, page, per_page


def latest_star_image(all_images):
    stars = [image for image in all_images if image["starred"]]
    if not stars:
        return None
    stars.sort(key=lambda image: image["mtime"], reverse=True)
    return stars[0]


@app.route("/")
def index():
    # Birds by default.
    mode = request.args.get("filter", "bird")
    species_query = request.args.get("species", "")

    if mode not in {"all", "bird", "motion", "star", "today", "species"}:
        mode = "bird"

    page = parse_int_arg("page", 1, 1, 100000)
    per_page = parse_int_arg("per_page", DEFAULT_PER_PAGE, 1, MAX_PER_PAGE)

    all_images = get_all_images()
    filtered_images = filter_images(all_images, mode, species_query)

    pages = split_pages(group_bursts(filtered_images), per_page)
    total_pages = len(pages)
    page = max(1, min(page, total_pages))
    page_groups = pages[page - 1]
    page_images = ordered_images(page_groups)
    page_numbers = make_page_numbers(page, total_pages)

    status = build_status(all_images)
    latest_star = latest_star_image(all_images)

    return render_template_string(
        HTML_TEMPLATE,
        images=page_images,
        groups=page_groups,
        count=len(page_images),
        total=len(all_images),
        filtered_total=len(filtered_images),
        page=page,
        total_pages=total_pages,
        page_numbers=page_numbers,
        per_page=per_page,
        mode=mode,
        species_query=species_query,
        status=status,
        latest_star=latest_star,
        capture_dir=str(CAPTURE_DIR),
        admin_mode=ADMIN_MODE,
        paris_species=PARIS_SPECIES_LIST,
        base_url=request.host_url.rstrip("/"),
        og_image_name=(latest_star["name"] if latest_star else
                       next((img["name"] for img in all_images if img["kind"] == "bird"), None)),
    )


def view_nav_args(source, species_key):
    """
    Filtre, espèce et taille de page transmis par la visionneuse. Dans les
    formulaires, le champ "species" est l'espèce choisie pour la correction :
    le filtre voyage donc sous "species_filter".
    """
    mode = source.get("filter", "bird")
    if mode not in {"all", "bird", "motion", "star", "today", "species"}:
        mode = "bird"
    species_query = source.get(species_key, "")
    try:
        per_page = max(1, min(int(source.get("per_page", DEFAULT_PER_PAGE)), MAX_PER_PAGE))
    except ValueError:
        per_page = DEFAULT_PER_PAGE
    return mode, species_query, per_page


def view_url(filename, mode, species_query, per_page):
    return url_for("view", filename=filename, filter=mode,
                   species=species_query or None, per_page=per_page)


def viewer_return(filename):
    """
    Pour une action lancée depuis la visionneuse, prépare la redirection :
    la photo elle-même (sous son nouveau nom) si elle reste dans le filtre,
    sinon la suivante, sinon la précédente, sinon la galerie.
    Renvoie None si l'action vient de la galerie.
    """
    if request.form.get("view") != "1":
        return None

    mode, species_query, per_page = view_nav_args(request.form, "species_filter")
    names = [image["name"] for image in ordered_images(group_bursts(filter_images(get_all_images(), mode, species_query)))]
    neighbours = []
    if filename in names:
        index = names.index(filename)
        neighbours = names[index + 1:index + 2] + names[max(0, index - 1):index]

    def go(new_name):
        # Les voisines ne changent pas de filtre ; seule la photo modifiée
        # est relue, sans reparcourir tout le dossier.
        if new_name and filter_images([parse_image_metadata(CAPTURE_DIR / new_name)], mode, species_query):
            return redirect(view_url(new_name, mode, species_query, per_page))
        for name in neighbours:
            if (CAPTURE_DIR / name).exists():
                return redirect(view_url(name, mode, species_query, per_page))
        return redirect(url_for("index", filter=mode, species=species_query or None, per_page=per_page))

    return go


@app.route("/view/<path:filename>")
def view(filename):
    # Les actions ne visent que la racine des captures : un sous-dossier
    # afficherait une photo et agirait sur une autre du même nom.
    if "/" in filename:
        abort(404)
    path = safe_image_path(filename)
    mode, species_query, per_page = view_nav_args(request.args, "species")

    groups = group_bursts(filter_images(get_all_images(), mode, species_query))
    images = ordered_images(groups)
    names = [image["name"] for image in images]

    if filename in names:
        index = names.index(filename)
        current = images[index]
        prev_name = names[index - 1] if index > 0 else None
        next_name = names[index + 1] if index + 1 < len(names) else None
        page = next(
            number for number, page_groups in enumerate(split_pages(groups, per_page), start=1)
            if any(image["name"] == filename for group in page_groups for image in group["images"])
        )
        position = index + 1
    else:
        # Photo hors du filtre (lien direct) : affichée sans navigation.
        current = parse_image_metadata(path)
        prev_name = next_name = None
        page = 1
        position = None

    gallery_url = url_for("index", filter=mode, species=species_query or None,
                          page=page, per_page=per_page) + "#" + filename

    return render_template_string(
        VIEW_TEMPLATE,
        image=current,
        prev_name=prev_name,
        next_name=next_name,
        position=position,
        total=len(names),
        gallery_url=gallery_url,
        mode=mode,
        species_query=species_query,
        per_page=per_page,
        admin_mode=ADMIN_MODE,
        paris_species=PARIS_SPECIES_LIST,
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
    require_admin()

    for path in THUMB_DIR.iterdir():
        if path.is_file():
            path.unlink()

    return redirect(url_for("index"))


@app.route("/delete/<path:filename>", methods=["POST"])
def delete_image(filename):
    require_admin()
    mode, page, per_page = current_nav_args_from_form()
    back = viewer_return(filename)

    delete_image_and_thumbnail(filename)

    if back:
        return back(None)

    return redirect(
        url_for(
            "index",
            filter=mode,
            page=page,
            per_page=per_page,
        )
    )


@app.route("/retag/<path:filename>", methods=["POST"])
def retag(filename):
    require_admin()
    mode, page, per_page = current_nav_args_from_form()
    new_tag = request.form.get("new_tag", "")
    back = viewer_return(filename)

    new_name = retag_image(filename, new_tag)

    if back:
        return back(new_name)

    return redirect(
        url_for(
            "index",
            filter=mode,
            page=page,
            per_page=per_page,
        )
    )


@app.route("/star/<path:filename>", methods=["POST"])
def star(filename):
    require_admin()
    mode, page, per_page = current_nav_args_from_form()
    back = viewer_return(filename)

    new_name = toggle_star_image(filename)

    if back:
        return back(new_name)

    return redirect(
        url_for(
            "index",
            filter=mode,
            page=page,
            per_page=per_page,
        )
    )


@app.route("/correct_species/<path:filename>", methods=["POST"])
def correct_species(filename):
    require_admin()
    path = safe_image_path(filename)

    scientific = request.form.get("species", "").strip()

    if not scientific:
        abort(400)

    back = viewer_return(filename)

    old_match = re.search(r"_sp([a-zA-Z0-9_-]+?)_spconf([0-9.]+)", path.name)
    was = old_match.group(1).replace("_", " ").title() if old_match else ""

    clean_stem = re.sub(r"_sp[a-zA-Z0-9_-]+?_spconf[0-9.]+$", "", path.stem)
    sp_slug = re.sub(r"[^a-z0-9_-]+", "_", scientific.lower())
    new_path = make_unique_path(path.parent / f"{clean_stem}_sp{sp_slug}_spconf1.00.jpg")
    delete_thumbnail(path.name)
    path.rename(new_path)

    append_correction(new_path.name, was, scientific)

    if back:
        return back(new_path.name)

    mode, page, per_page = current_nav_args_from_form()
    return redirect(url_for("index", filter=mode, page=page, per_page=per_page))


def clear_species_tag(path: Path):
    """Retire le suffixe _sp..._spconf... du nom de fichier."""
    new_stem = re.sub(r"_sp[a-zA-Z0-9_-]+?_spconf[0-9.]+$", "", path.stem)
    if new_stem == path.stem:
        return path.name
    old_match = re.search(r"_sp([a-zA-Z0-9_-]+?)_spconf", path.name)
    was = old_match.group(1).replace("_", " ").title() if old_match else ""
    new_path = make_unique_path(path.parent / (new_stem + path.suffix))
    delete_thumbnail(path.name)
    path.rename(new_path)
    # now="" : espèce retirée à la main, retag_history.py ne la remettra pas.
    append_correction(new_path.name, was, "")
    return new_path.name


@app.route("/clear_species/<path:filename>", methods=["POST"])
def clear_species(filename):
    require_admin()
    path = safe_image_path(filename)
    back = viewer_return(filename)
    new_name = clear_species_tag(path)
    if back:
        return back(new_name)
    mode, page, per_page = current_nav_args_from_form()
    return redirect(url_for("index", filter=mode, page=page, per_page=per_page))


@app.route("/bulk_action", methods=["POST"])
def bulk_action():
    require_admin()
    action    = request.form.get("action", "")
    filenames = request.form.getlist("filenames")
    scientific = request.form.get("species", "").strip()
    mode, page, per_page = current_nav_args_from_form()

    for filename in filenames:
        try:
            path = safe_image_path(filename)
        except Exception:
            continue
        if action == "delete":
            delete_image_and_thumbnail(filename)
        elif action in ("bird", "motion"):
            retag_image(filename, action)
        elif action == "star":
            toggle_star_image(filename)
        elif action == "clear_species":
            clear_species_tag(path)
        elif action == "correct_species" and scientific:
            old_match = re.search(r"_sp([a-zA-Z0-9_-]+?)_spconf([0-9.]+)", path.name)
            was = old_match.group(1).replace("_", " ").title() if old_match else ""
            clean_stem = re.sub(r"_sp[a-zA-Z0-9_-]+?_spconf[0-9.]+$", "", path.stem)
            sp_slug = re.sub(r"[^a-z0-9_-]+", "_", scientific.lower())
            new_path = make_unique_path(path.parent / f"{clean_stem}_sp{sp_slug}_spconf1.00.jpg")
            delete_thumbnail(path.name)
            path.rename(new_path)
            append_correction(new_path.name, was, scientific)

    return redirect(url_for("index", filter=mode, page=page, per_page=per_page))

@app.route("/camera/toggle", methods=["POST"])
def camera_toggle():
    require_admin()

    mode, page, per_page = current_nav_args_from_form()

    # La caméra est tenue par le clip : y toucher la ferait échouer en boucle.
    if service_status(CLIP_SERVICE)["active"]:
        return redirect(url_for("index", filter=mode, page=page, per_page=per_page))

    svc = service_status("birdcam")
    action = "stop" if svc["active"] else "start"

    try:
        subprocess.run(
            ["sudo", "systemctl", action, "birdcam"],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass

    return redirect(url_for("index", filter=mode, page=page, per_page=per_page))


@app.route("/camera/test", methods=["POST"])
def camera_test():
    require_admin()

    mode, page, per_page = current_nav_args_from_form()

    # La caméra est tenue par le clip : y toucher la ferait échouer en boucle.
    if service_status(CLIP_SERVICE)["active"]:
        return redirect(url_for("index", filter=mode, page=page, per_page=per_page))

    run_camera_test()

    return redirect(url_for("index", filter=mode, page=page, per_page=per_page))


@app.route("/camera-test-image")
def camera_test_image():
    require_admin()

    if not CAMERA_TEST_IMAGE_PATH.exists():
        abort(404)

    return send_from_directory(
        CAMERA_TEST_IMAGE_PATH.parent, CAMERA_TEST_IMAGE_PATH.name
    )


def list_clips():
    if not CLIPS_DIR.exists():
        return []

    clips = []
    for path in CLIPS_DIR.iterdir():
        match = CLIP_NAME_RE.match(path.name)
        if not match or not path.is_file():
            continue
        taken = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
        clips.append({
            "name": path.name,
            "date": taken.strftime("%Y-%m-%d %H:%M:%S"),
            "size_mb": f"{path.stat().st_size / (1024 ** 2):.1f}",
        })

    clips.sort(key=lambda clip: clip["name"], reverse=True)
    return clips


def safe_clip_name(filename):
    if not CLIP_NAME_RE.match(filename) or not (CLIPS_DIR / filename).is_file():
        abort(404)
    return filename


@app.route("/clips")
def clips_page():
    return render_template_string(
        CLIPS_TEMPLATE,
        clips=list_clips(),
        waiting=service_status(CLIP_SERVICE)["active"],
        admin_mode=ADMIN_MODE,
    )


@app.route("/clip/<path:filename>")
def clip_file(filename):
    # send_from_directory gère les requêtes Range, nécessaires à la lecture dans le navigateur.
    return send_from_directory(CLIPS_DIR, safe_clip_name(filename), mimetype="video/mp4")


@app.route("/clip/request", methods=["POST"])
def clip_request():
    require_admin()

    # Le clip rend la caméra à la capture photo en finissant : on ne le lance
    # pas si la caméra a été arrêtée volontairement, ni s'il attend déjà.
    if service_status("birdcam")["active"] and not service_status(CLIP_SERVICE)["active"]:
        try:
            result = subprocess.run(
                ["sudo", "systemctl", "start", "--no-block", CLIP_SERVICE],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return "Le lancement du clip a dépassé 5 s.", 504
        if result.returncode != 0:
            # Typiquement : unité absente, install_services.sh n'a pas été relancé.
            return f"Le clip n'a pas pu être lancé : {result.stderr.strip()}", 502

    return redirect(url_for("index"))


@app.route("/clip/cancel", methods=["POST"])
def clip_cancel():
    require_admin()

    try:
        subprocess.run(
            ["sudo", "systemctl", "stop", CLIP_SERVICE],
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        pass

    return redirect(url_for("index"))


@app.route("/clip/delete/<path:filename>", methods=["POST"])
def clip_delete(filename):
    require_admin()
    (CLIPS_DIR / safe_clip_name(filename)).unlink()
    return redirect(url_for("clips_page"))


@app.route("/stats")
def stats_page():
    all_images = get_all_images()
    stats = build_stats(all_images)

    return render_template_string(
        STATS_TEMPLATE,
        stats=stats,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "0.0.0.0")

    app.run(
        host=host,
        port=port,
        debug=False,
    )
