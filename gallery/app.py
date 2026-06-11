#!/usr/bin/env python3

from flask import Flask, render_template_string, send_from_directory, abort, request, redirect, url_for
from pathlib import Path
from datetime import datetime, date
import subprocess
import shutil
import math
import re
import json
import cv2
import os


app = Flask(__name__)

CAPTURE_DIR = Path.home() / "birdcam" / "captures"
THUMB_DIR = Path.home() / "birdcam" / "gallery" / "thumbs"

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


def french_name(display_name: str) -> str:
    """Retourne le nom français pour un nom affiché type 'Parus Major', ou '' si inconnu."""
    return FRENCH_NAMES.get(display_name.lower(), "")


def append_correction(image_name: str, was: str, now: str):
    from datetime import datetime
    entry = {"image": image_name, "was": was, "now": now,
             "corrected_at": datetime.now().isoformat(timespec="seconds")}
    data = []
    if CORRECTIONS_PATH.exists():
        try:
            data = json.loads(CORRECTIONS_PATH.read_text())
        except Exception:
            pass
    data.append(entry)
    CORRECTIONS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{{ "Birdcam Admin" if admin_mode else "Birdcam Gallery" }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">

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
            height: 360px;
            object-fit: cover;
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

        .card-extra {
            margin-top: 0.1rem;
        }

        .card-extra summary {
            cursor: pointer;
            list-style: none;
            color: var(--muted);
            font-size: 0.8rem;
        }

        .card-extra summary::-webkit-details-marker { display: none; }

        .card-extra summary::after {
            content: " ↓";
            font-size: 0.7rem;
            opacity: 0.5;
        }

        .card-extra[open] summary::after {
            content: " ↑";
        }

        .card-extra > div {
            font-size: 0.78rem;
            color: var(--muted);
            margin-top: 0.15rem;
            padding-left: 0.4rem;
            border-left: 2px solid var(--border);
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
                grid-template-columns: 1fr;
            }

            .latest-star img {
                height: 240px;
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
        }

        .bar-bird-fill {
            background: var(--bird);
            height: 100%;
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
            <a href="/?filter=species&species={{ sp.name }}">{% if sp.french %}{{ sp.french }}{% else %}{{ sp.name }}{% endif %}</a><span class="sp-count">{{ sp.count }}</span>{% if not loop.last %}<span class="sep"> · </span>{% endif %}
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
        <div class="status-item">Birds: {{ status.bird_count }}</div>
        <div class="status-item">Stars: {{ status.star_count }}</div>
        <div class="status-item">Today: {{ status.today_count }}</div>
        <div class="status-item">Motion: {{ status.motion_count }}</div>
        {% if status.top_species %}
        <div class="status-item">
            Top : {% for sp in status.top_species %}<a href="/?filter=species&species={{ sp.name }}" style="color:inherit">{{ sp.name }}{% if sp.french %} ({{ sp.french }}){% endif %}</a> {{ sp.count }}{% if not loop.last %} · {% endif %}{% endfor %}
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
    <a href="/image/{{ latest_star.name }}" target="_blank">
        <div class="latest-star-inner">
            <img src="/thumb/{{ latest_star.name }}" alt="{{ latest_star.name }}">
            <div class="latest-star-text">
                <div class="latest-star-kicker">Latest star</div>
                <div class="latest-star-title">A favourite visitor from the feeder</div>
                <div class="latest-star-meta">
                    {{ latest_star.date }}<br>
                    {{ latest_star.name }}<br>
                    Confidence: {{ latest_star.confidence }} · Best: {{ latest_star.best_label }}
                </div>
            </div>
        </div>
    </a>
</section>
{% endif %}

{% if images %}
<main class="gallery">
    {% for image in images %}
    <div class="card" id="card-{{ loop.index }}">
        <span class="badge {{ image.kind_class }}">{{ image.kind_label }}</span>
        {% if image.starred %}
        <span class="badge star">STAR</span>
        {% endif %}

        {% if admin_mode %}
        <label class="card-cb-wrap" onclick="event.stopPropagation()">
            <input type="checkbox" class="bulk-cb" value="{{ image.name }}">
        </label>
        {% endif %}

        <a href="/image/{{ image.name }}" target="_blank">
            <img src="/thumb/{{ image.name }}" loading="lazy" alt="{{ image.name }}">
        </a>

        <div class="meta">
            <div class="filename">{{ image.name }}</div>

            <div class="details">
                <div>{{ image.date }}</div>
                <details class="card-extra">
                    <summary>
                        {% if image.species %}Espèce : {{ image.species }} ({{ image.species_conf }})
                        {% else %}Best: {{ image.best_label }}{% endif %}
                    </summary>
                    <div>Confidence: {{ image.confidence }}</div>
                    <div>Motion score: {{ image.motion_score }}</div>
                </details>
                {% if admin_mode and paris_species %}
                <details class="correct-species-wrap">
                    <summary>✎ Correct species</summary>
                    <form class="correct-species-form" method="post" action="/correct_species/{{ image.name }}">
                        <input type="hidden" name="filter" value="{{ mode }}">
                        <input type="hidden" name="page" value="{{ page }}">
                        <input type="hidden" name="per_page" value="{{ per_page }}">
                        <select name="species">
                            {% for sp in paris_species %}
                            <option value="{{ sp.scientific }}">{{ sp.french }} ({{ sp.scientific }})</option>
                            {% endfor %}
                        </select>
                        <button type="submit">OK</button>
                    </form>
                </details>
                {% endif %}
            </div>

        </div>
    </div>
    {% endfor %}
</main>
{% else %}
<div class="empty">
    No pictures found for this filter in {{ capture_dir }}.
</div>
{% endif %}

<div class="bottom-nav">
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
                <div class="bar-bird-fill" style="width: {{ (sp.count / status.top_species[0].count * 100) | round(1) }}%"></div>
            </div>
            <div class="bar-count">{{ sp.count }}</div>
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
        <button type="button" class="bk-btn bk-species" onclick="bulkSubmit('clear_species')">Clear species</button>
        <button type="button" class="bk-btn bk-del"     onclick="bulkSubmit('delete')">Delete</button>
        <button type="button" class="bk-btn bk-cancel"  onclick="clearSelection()">Cancel</button>
    </div>
    <form id="bulk-form" method="post" action="/bulk_action" style="display:none">
        <input type="hidden" name="filter" value="{{ mode }}">
        <input type="hidden" name="page" value="{{ page }}">
        <input type="hidden" name="per_page" value="{{ per_page }}">
        <input type="hidden" name="action" id="bulk-action-val">
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
        if (action === "delete" && !confirm("Supprimer " + checked.length + " photo(s) ?")) return;
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

    function clearSelection() {
        document.querySelectorAll(".bulk-cb").forEach(cb => {
            cb.checked = false;
            cb.closest(".card").classList.remove("selected");
        });
        updateBulkBar();
    }

    document.querySelectorAll(".bulk-cb").forEach(cb => {
        cb.addEventListener("change", function () {
            this.closest(".card").classList.toggle("selected", this.checked);
            updateBulkBar();
        });
    });
</script>

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
        Based on AI classification of bird pictures (iNaturalist model).
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
                    <div class="bar-bird" style="width: {{ (sp.count / stats.max_species_count * 100) | round(1) }}%"></div>
                </div>
                <div class="bar-value">{{ sp.count }}</div>
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
    species_match = re.search(r"_sp([a-zA-Z0-9_-]+?)_spconf([0-9.]+)", clean_name)

    confidence = confidence_match.group(1) if confidence_match else "n/a"
    best_label = best_match.group(1) if best_match else "n/a"
    motion_score = motion_match.group(1) if motion_match else "n/a"
    species = species_match.group(1).replace("_", " ").title() if species_match else None
    species_conf = species_match.group(2) if species_match else None

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
    today_key = date.today().strftime("%Y-%m-%d")

    free_gb = disk.free / (1024 ** 3)
    total_gb = disk.total / (1024 ** 3)
    used_percent = (disk.used / disk.total) * 100

    # Top espèces : compter les species uniques sur les photos bird_
    species_counts = {}
    for image in all_images:
        if image["kind"] == "bird" and image.get("species"):
            sp = image["species"]
            species_counts[sp] = species_counts.get(sp, 0) + 1
    top_species = [
        {"name": sp, "count": n, "french": french_name(sp)}
        for sp, n in sorted(species_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    return {
        "birdcam_service": service_status("birdcam"),
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

    species_counts = {}
    for image in all_images:
        if image["kind"] == "bird" and image.get("species"):
            sp = image["species"]
            species_counts[sp] = species_counts.get(sp, 0) + 1
    top_species = [
        {"name": sp, "count": n, "french": french_name(sp)}
        for sp, n in sorted(species_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ]
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

    page_images, page, total_pages = paginate_images(filtered_images, page, per_page)
    page_numbers = make_page_numbers(page, total_pages)

    status = build_status(all_images)
    latest_star = latest_star_image(all_images)

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
        species_query=species_query,
        status=status,
        latest_star=latest_star,
        capture_dir=str(CAPTURE_DIR),
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
    mode, page, per_page = current_nav_args_from_form()

    delete_image_and_thumbnail(filename)

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
    mode, page, per_page = current_nav_args_from_form()
    new_tag = request.form.get("new_tag", "")

    retag_image(filename, new_tag)

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
    mode, page, per_page = current_nav_args_from_form()

    toggle_star_image(filename)

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

    old_match = re.search(r"_sp([a-zA-Z0-9_-]+?)_spconf([0-9.]+)", path.name)
    was = old_match.group(1).replace("_", " ").title() if old_match else ""

    clean_stem = re.sub(r"_sp[a-zA-Z0-9_-]+?_spconf[0-9.]+$", "", path.stem)
    sp_slug = re.sub(r"[^a-z0-9_-]+", "_", scientific.lower())
    new_path = make_unique_path(path.parent / f"{clean_stem}_sp{sp_slug}_spconf1.00.jpg")
    delete_thumbnail(path.name)
    path.rename(new_path)

    append_correction(new_path.name, was, scientific)

    mode, page, per_page = current_nav_args_from_form()
    return redirect(url_for("index", filter=mode, page=page, per_page=per_page))


def clear_species_tag(path: Path):
    """Retire le suffixe _sp..._spconf... du nom de fichier."""
    new_stem = re.sub(r"_sp[a-zA-Z0-9_-]+?_spconf[0-9.]+$", "", path.stem)
    if new_stem == path.stem:
        return
    new_path = make_unique_path(path.parent / (new_stem + path.suffix))
    delete_thumbnail(path.name)
    path.rename(new_path)


@app.route("/clear_species/<path:filename>", methods=["POST"])
def clear_species(filename):
    require_admin()
    path = safe_image_path(filename)
    clear_species_tag(path)
    mode, page, per_page = current_nav_args_from_form()
    return redirect(url_for("index", filter=mode, page=page, per_page=per_page))


@app.route("/bulk_action", methods=["POST"])
def bulk_action():
    require_admin()
    action    = request.form.get("action", "")
    filenames = request.form.getlist("filenames")
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

    return redirect(url_for("index", filter=mode, page=page, per_page=per_page))


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
