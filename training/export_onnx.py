#!/usr/bin/env python3
"""
Exporte le modèle entraîné vers ONNX compatible OpenCV DNN (cv2.dnn.readNetFromONNX).

Usage :
    python3 training/export_onnx.py --model training/model_best.pth \
                                    --out   /tmp/garden_birds.onnx
    # Puis copier sur le Pi :
    scp /tmp/garden_birds.onnx fx@oaso.local:~/birdcam/model/
"""

import argparse
import json
from pathlib import Path

import torch
import torch.nn as nn
import timm


IMG_SIZE = 224

# Normalisation ImageNet intégrée dans le modèle.
# Le modèle accepte ainsi des valeurs brutes [0, 255] float32 (NCHW),
# ce qui est compatible avec cv2.dnn.blobFromImage(scalefactor=1/255).
_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
_STD  = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


class NormalizedModel(nn.Module):
    def __init__(self, backbone):
        super().__init__()
        self.backbone = backbone
        self.register_buffer("mean", _MEAN)
        self.register_buffer("std",  _STD)

    def forward(self, x):
        x = x / 255.0
        x = (x - self.mean) / self.std
        return self.backbone(x)


def export(model_path: str, out_path: str):
    ckpt   = torch.load(model_path, map_location="cpu", weights_only=False)
    classes = ckpt["classes"]
    n_cls  = len(classes)

    backbone = timm.create_model("efficientnet_b0", pretrained=False, num_classes=n_cls)
    backbone.load_state_dict(ckpt["model"])
    model = NormalizedModel(backbone)
    model.eval()

    dummy = torch.zeros(1, 3, IMG_SIZE, IMG_SIZE)  # [0, 255] float32

    torch.onnx.export(
        model,
        dummy,
        out_path,
        opset_version=12,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
    )

    # Sauvegarder les labels dans un CSV compatible avec birdcam_motion.py
    labels_path = Path(out_path).with_name("garden_birds_labels.csv")
    with open(labels_path, "w") as f:
        f.write("id,name\n")
        for i, cls in enumerate(classes):
            # Le nom du dossier est le nom scientifique avec underscores
            # On le convertit en nom lisible : parus_major → Parus major
            readable = cls.replace("_", " ").title()
            f.write(f"{i},{readable}\n")

    print(f"ONNX exporté   : {out_path}  ({Path(out_path).stat().st_size // 1024} Ko)")
    print(f"Labels exportés : {labels_path}  ({n_cls} classes)")
    print(f"\nCopier sur le Pi :")
    print(f"  scp {out_path} fx@oaso.local:~/birdcam/model/garden_birds.onnx")
    print(f"  scp {labels_path} fx@oaso.local:~/birdcam/model/")
    print(f"\nPuis dans birdcam_motion.py, changer :")
    print(f'  SPECIES_MODEL_PATH  = MODEL_DIR / "garden_birds.onnx"')
    print(f'  SPECIES_LABELS_PATH = MODEL_DIR / "garden_birds_labels.csv"')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="training/model_best.pth")
    parser.add_argument("--out",   default="/tmp/garden_birds.onnx")
    args = parser.parse_args()
    export(args.model, args.out)


if __name__ == "__main__":
    main()
