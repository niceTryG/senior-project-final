from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a local YOLO garment detector.")
    parser.add_argument("--data", required=True, help="Path to dataset.yaml")
    parser.add_argument("--model", default="yolo11n.pt", help="YOLO base weights to start from")
    parser.add_argument("--epochs", type=int, default=80, help="Training epochs")
    parser.add_argument("--imgsz", type=int, default=960, help="Training image size")
    parser.add_argument("--batch", type=int, default=8, help="Batch size")
    parser.add_argument("--device", default="0", help="Device, for example 0 or cpu")
    parser.add_argument("--project", default="runs/detect", help="Output project directory")
    parser.add_argument("--name", default="garment_parts", help="Run name")
    parser.add_argument("--patience", type=int, default=20, help="Early stopping patience")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_path = Path(args.data).resolve()
    if not data_path.exists():
        raise SystemExit(f"Dataset file not found: {data_path}")

    try:
        from ultralytics import YOLO
    except ModuleNotFoundError:
        print("Ultralytics is not installed. Run `pip install -r requirements-garment-ai.txt` first.")
        return 1

    print(
        "Running YOLO training with "
        f"model={args.model}, data={data_path.as_posix()}, epochs={args.epochs}, "
        f"imgsz={args.imgsz}, batch={args.batch}, device={args.device}"
    )

    model = YOLO(args.model)
    model.train(
        data=data_path.as_posix(),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
        patience=args.patience,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
