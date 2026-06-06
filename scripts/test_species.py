#!/usr/bin/env python3
"""
Test autonome du classifieur d'espèces — ne nécessite pas la caméra.

Usage :
    python3 scripts/test_species.py
    python3 scripts/test_species.py --image /path/to/bird.jpg
"""

import sys
import argparse
import numpy as np
from pathlib import Path

BASE_DIR = Path.home() / "birdcam"
MODEL_DIR = BASE_DIR / "model"
SPECIES_MODEL_PATH = MODEL_DIR / "aiy_vision_classifier_birds_V1_3.tflite"
SPECIES_LABELS_PATH = MODEL_DIR / "aiy_birds_V1_labelmap.csv"


def check_tflite():
    try:
        from ai_edge_litert.interpreter import Interpreter
        print("✓ ai-edge-litert disponible")
        return Interpreter
    except ImportError:
        pass
    try:
        from tflite_runtime.interpreter import Interpreter
        print("✓ tflite-runtime disponible")
        return Interpreter
    except ImportError:
        print("✗ TFLite non installé — faire : pip install ai-edge-litert")
        sys.exit(1)


def load_labels(path):
    labels = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("id"):
                continue
            parts = line.split(",", 1)
            if len(parts) == 2:
                try:
                    labels[int(parts[0])] = parts[1].strip()
                except ValueError:
                    pass
    return labels


def run_inference(interpreter, input_details, output_details, image_rgb):
    resized = __import__("cv2").resize(image_rgb, (224, 224))
    input_data = np.expand_dims(resized, axis=0)
    if input_details[0]["dtype"] == np.float32:
        input_data = input_data.astype(np.float32) / 255.0
    interpreter.set_tensor(input_details[0]["index"], input_data)
    interpreter.invoke()
    return interpreter.get_tensor(output_details[0]["index"])[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", help="Chemin vers une image JPEG de test")
    args = parser.parse_args()

    print(f"\n--- Test classifieur d'espèces ---")

    # 1. TFLite
    Interpreter = check_tflite()

    # 2. Fichiers modèle
    for path in (SPECIES_MODEL_PATH, SPECIES_LABELS_PATH):
        if not path.exists():
            print(f"✗ Fichier manquant : {path}")
            print("  → Lancer : bash scripts/install_models.sh")
            sys.exit(1)
        print(f"✓ {path.name} ({path.stat().st_size // 1024} Ko)")

    # 3. Chargement
    interpreter = Interpreter(model_path=str(SPECIES_MODEL_PATH))
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    print(f"✓ Modèle chargé  — entrée : {input_details[0]['shape']}  dtype : {input_details[0]['dtype'].__name__}")

    labels = load_labels(SPECIES_LABELS_PATH)
    print(f"✓ Labels chargés : {len(labels)} espèces")

    # 4. Inférence
    import cv2
    if args.image:
        img_bgr = cv2.imread(args.image)
        if img_bgr is None:
            print(f"✗ Impossible de lire : {args.image}")
            sys.exit(1)
        image_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        print(f"✓ Image chargée : {args.image}")
    else:
        # Image synthétique : fond vert + tache marron au centre (simule un oiseau)
        image_rgb = np.full((480, 640, 3), (80, 120, 60), dtype=np.uint8)
        image_rgb[180:300, 270:370] = (120, 80, 40)
        print("✓ Image synthétique générée (résultat non significatif)")

    output = run_inference(interpreter, input_details, output_details, image_rgb)

    top5 = np.argsort(output)[::-1][:5]
    print("\nTop 5 prédictions :")
    for rank, idx in enumerate(top5, 1):
        score = float(output[idx])
        name = labels.get(idx, f"idx_{idx}")
        bar = "█" * int(score * 40)
        print(f"  {rank}. {name:<40s}  {score:.4f}  {bar}")

    print("\n✓ Test terminé avec succès.")


if __name__ == "__main__":
    main()
