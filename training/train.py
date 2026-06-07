#!/usr/bin/env python3
"""
Fine-tune EfficientNet-B0 sur les espèces de jardins parisiens.

Prérequis :
    pip install torch torchvision timm pillow tqdm

Usage :
    python3 training/train.py --data dataset/ --epochs 30
    python3 training/train.py --data dataset/ --epochs 5 --quick   # test rapide
"""

import argparse
import json
import random
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split
from torchvision import datasets, transforms
from tqdm import tqdm

try:
    import timm
except ImportError:
    raise SystemExit("pip install timm")


# ── Hyperparamètres ──────────────────────────────────────────────────────────

IMG_SIZE    = 224
BATCH_SIZE  = 32
LR_HEAD     = 1e-3
LR_FULL     = 1e-4
WARMUP_EPOCHS = 3    # entraîne seulement la tête
VAL_SPLIT   = 0.15
SEED        = 42


# ── Augmentations ────────────────────────────────────────────────────────────

train_tf = transforms.Compose([
    transforms.RandomResizedCrop(IMG_SIZE, scale=(0.6, 1.0)),
    transforms.RandomHorizontalFlip(),
    transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.2),
    transforms.RandomRotation(15),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])

val_tf = transforms.Compose([
    transforms.Resize(int(IMG_SIZE * 1.15)),
    transforms.CenterCrop(IMG_SIZE),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_device():
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")   # Apple Silicon
    return torch.device("cpu")


def accuracy(logits, labels):
    return (logits.argmax(1) == labels).float().mean().item()


def train_epoch(model, loader, optimizer, criterion, device):
    model.train()
    loss_sum = acc_sum = 0
    for imgs, labels in loader:
        imgs, labels = imgs.to(device), labels.to(device)
        optimizer.zero_grad()
        out  = model(imgs)
        loss = criterion(out, labels)
        loss.backward()
        optimizer.step()
        loss_sum += loss.item()
        acc_sum  += accuracy(out, labels)
    n = len(loader)
    return loss_sum / n, acc_sum / n


@torch.no_grad()
def eval_epoch(model, loader, criterion, device):
    model.eval()
    loss_sum = acc_sum = 0
    for imgs, labels in loader:
        imgs, labels = imgs.to(device), labels.to(device)
        out  = model(imgs)
        loss = criterion(out, labels)
        loss_sum += loss.item()
        acc_sum  += accuracy(out, labels)
    n = len(loader)
    return loss_sum / n, acc_sum / n


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data",    required=True,  help="Dossier dataset/")
    parser.add_argument("--epochs",  type=int, default=30)
    parser.add_argument("--out",     default="training/model_best.pth")
    parser.add_argument("--quick",   action="store_true", help="5 epochs, debug")
    args = parser.parse_args()

    if args.quick:
        args.epochs = 5

    random.seed(SEED)
    torch.manual_seed(SEED)

    device = get_device()
    print(f"Device : {device}")

    # ── Dataset ──────────────────────────────────────────────────────────────
    full_ds = datasets.ImageFolder(args.data, transform=train_tf)
    n_val   = max(1, int(len(full_ds) * VAL_SPLIT))
    n_train = len(full_ds) - n_val
    train_ds, val_ds = random_split(full_ds, [n_train, n_val],
                                    generator=torch.Generator().manual_seed(SEED))
    # Appliquer les transformations val sur le sous-ensemble de validation
    val_ds.dataset = datasets.ImageFolder(args.data, transform=val_tf)

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,  num_workers=2)
    val_loader   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False, num_workers=2)

    classes = full_ds.classes
    n_cls   = len(classes)
    print(f"{n_train} train / {n_val} val  —  {n_cls} classes")

    # Sauvegarder le mapping classe → index
    mapping = {i: cls for i, cls in enumerate(classes)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).with_suffix(".json").write_text(json.dumps(mapping, indent=2))

    # ── Modèle ───────────────────────────────────────────────────────────────
    model = timm.create_model("efficientnet_b0", pretrained=True, num_classes=n_cls)
    model = model.to(device)

    criterion = nn.CrossEntropyLoss(label_smoothing=0.1)
    best_val_acc = 0.0

    # Phase 1 : entraîne seulement la tête de classification
    for param in model.parameters():
        param.requires_grad = False
    for param in model.classifier.parameters():
        param.requires_grad = True

    optimizer = torch.optim.AdamW(model.classifier.parameters(), lr=LR_HEAD)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, WARMUP_EPOCHS)

    print(f"\nPhase 1 : tête seule ({WARMUP_EPOCHS} epochs)")
    for epoch in range(1, WARMUP_EPOCHS + 1):
        tr_loss, tr_acc = train_epoch(model, train_loader, optimizer, criterion, device)
        va_loss, va_acc = eval_epoch(model, val_loader, criterion, device)
        scheduler.step()
        print(f"  Ep {epoch:02d}  train {tr_acc:.3f}  val {va_acc:.3f}  loss {va_loss:.3f}")

    # Phase 2 : déverrouille tout
    for param in model.parameters():
        param.requires_grad = True

    optimizer = torch.optim.AdamW(model.parameters(), lr=LR_FULL, weight_decay=1e-4)
    remaining = args.epochs - WARMUP_EPOCHS
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, remaining)

    print(f"\nPhase 2 : réseau complet ({remaining} epochs)")
    for epoch in range(WARMUP_EPOCHS + 1, args.epochs + 1):
        tr_loss, tr_acc = train_epoch(model, train_loader, optimizer, criterion, device)
        va_loss, va_acc = eval_epoch(model, val_loader, criterion, device)
        scheduler.step()
        mark = " ← best" if va_acc > best_val_acc else ""
        print(f"  Ep {epoch:02d}  train {tr_acc:.3f}  val {va_acc:.3f}  loss {va_loss:.3f}{mark}")
        if va_acc > best_val_acc:
            best_val_acc = va_acc
            torch.save({"model": model.state_dict(), "classes": classes}, args.out)

    print(f"\nMeilleur val acc : {best_val_acc:.3f}  →  {args.out}")


if __name__ == "__main__":
    main()
