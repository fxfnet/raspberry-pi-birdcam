#!/usr/bin/env python3
"""
Télécharge les photos d'observations iNaturalist pour les espèces de jardins parisiens.
Filtre : grade=research, licence libre, localisation France (place_id=6753).

Usage :
    pip install requests tqdm pillow
    python3 training/download_dataset.py --out dataset/ [--per-species 300]
"""

import argparse
import json
import time
import sys
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import URLError

import requests
from tqdm import tqdm

INAT_API    = "https://api.inaturalist.org/v1/observations"
PLACE_FRANCE = 6753
LICENSES    = "cc0,cc-by,cc-by-nc"
PAGE_SIZE   = 200
SLEEP_API   = 1.0   # secondes entre requêtes API
SLEEP_IMG   = 0.3   # secondes entre téléchargements d'images


def fetch_observation_page(taxon_name, page, per_page=PAGE_SIZE):
    params = {
        "taxon_name":   taxon_name,
        "quality_grade": "research",
        "photos":        "true",
        "photo_license": LICENSES,
        "place_id":      PLACE_FRANCE,
        "per_page":      per_page,
        "page":          page,
        "order":         "desc",
        "order_by":      "votes",   # photos les mieux notées en premier
    }
    r = requests.get(INAT_API, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def collect_photo_urls(taxon_name, max_photos):
    """Retourne une liste de (url, obs_id) jusqu'à max_photos."""
    urls = []
    page = 1
    while len(urls) < max_photos:
        data = fetch_observation_page(taxon_name, page)
        results = data.get("results", [])
        if not results:
            break
        for obs in results:
            for photo in obs.get("photos", []):
                url = photo.get("url", "")
                # Remplace /square. par /medium. pour obtenir 500px
                url = url.replace("/square.", "/medium.")
                if url:
                    urls.append((url, obs["id"]))
                    if len(urls) >= max_photos:
                        break
            if len(urls) >= max_photos:
                break
        total = data.get("total_results", 0)
        if page * PAGE_SIZE >= total:
            break
        page += 1
        time.sleep(SLEEP_API)
    return urls


def download_photos(urls, out_dir: Path, taxon_slug: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    downloaded = skipped = errors = 0
    for url, obs_id in tqdm(urls, desc=taxon_slug, unit="img"):
        ext = Path(url.split("?")[0]).suffix or ".jpg"
        dest = out_dir / f"{obs_id}{ext}"
        if dest.exists():
            skipped += 1
            continue
        try:
            urlretrieve(url, dest)
            downloaded += 1
            time.sleep(SLEEP_IMG)
        except (URLError, Exception) as e:
            print(f"\n  ERREUR {url}: {e}", file=sys.stderr)
            errors += 1
    return downloaded, skipped, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",         default="dataset",  help="Dossier de sortie")
    parser.add_argument("--species",     default="training/species.json")
    parser.add_argument("--per-species", type=int, default=300)
    args = parser.parse_args()

    species_list = json.loads(Path(args.species).read_text())
    out_root     = Path(args.out)

    print(f"{len(species_list)} espèces · {args.per_species} photos max par espèce")
    print(f"Sortie : {out_root.resolve()}\n")

    total_dl = total_skip = total_err = 0

    for sp in species_list:
        name  = sp["scientific"]
        slug  = name.lower().replace(" ", "_")
        fr    = sp["french"]
        out_dir = out_root / slug

        existing = list(out_dir.glob("*.jpg")) + list(out_dir.glob("*.jpeg"))
        already  = len(existing)
        needed   = max(0, args.per_species - already)

        if needed == 0:
            print(f"  OK (déjà {already})  {fr} ({name})")
            continue

        print(f"\n→ {fr} ({name}) — {already} existantes, besoin de {needed}")

        try:
            urls = collect_photo_urls(name, args.per_species)
            # Ne télécharger que les nouvelles
            obs_ids = {p.stem for p in existing}
            urls = [(u, oid) for u, oid in urls if str(oid) not in obs_ids]
            dl, sk, err = download_photos(urls[:needed], out_dir, slug)
            total_dl += dl; total_skip += sk; total_err += err
            print(f"  {dl} téléchargées, {sk} ignorées, {err} erreurs")
        except Exception as e:
            print(f"  ERREUR pour {name}: {e}", file=sys.stderr)
            total_err += 1

    print(f"\n{'='*50}")
    print(f"Total : {total_dl} téléchargées, {total_skip} ignorées, {total_err} erreurs")
    print(f"Dataset : {out_root.resolve()}")


if __name__ == "__main__":
    main()
