from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local YOLO garment prediction and export JSON.")
    parser.add_argument("--weights", required=True, help="Path to trained weights, usually best.pt")
    parser.add_argument("--image", required=True, help="Image path")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--imgsz", type=int, default=960, help="Inference image size")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--device", default="0", help="Device, for example 0 or cpu")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    weights_path = Path(args.weights).resolve()
    image_path = Path(args.image).resolve()
    output_path = Path(args.output).resolve()

    if not weights_path.exists():
        raise SystemExit(f"Weights not found: {weights_path}")
    if not image_path.exists():
        raise SystemExit(f"Image not found: {image_path}")

    try:
        from ultralytics import YOLO
    except ModuleNotFoundError:
        print("Ultralytics is not installed. Run `pip install -r requirements-garment-ai.txt` first.")
        return 1

    model = YOLO(str(weights_path))
    results = model.predict(
        source=str(image_path),
        imgsz=args.imgsz,
        conf=args.conf,
        device=args.device,
        verbose=False,
    )

    detections: list[dict] = []
    for result in results:
        names = getattr(result, "names", {}) or {}
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue

        xyxy = boxes.xyxy.cpu().tolist()
        confs = boxes.conf.cpu().tolist()
        classes = boxes.cls.cpu().tolist()

        for box, score, cls_id in zip(xyxy, confs, classes):
            left, top, right, bottom = [float(value) for value in box]
            detections.append(
                {
                    "class_id": int(cls_id),
                    "class_name": str(names.get(int(cls_id), cls_id)),
                    "confidence": round(float(score), 4),
                    "box": {
                        "left": round(left, 2),
                        "top": round(top, 2),
                        "right": round(right, 2),
                        "bottom": round(bottom, 2),
                        "width": round(right - left, 2),
                        "height": round(bottom - top, 2),
                    },
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "image": image_path.as_posix(),
                "weights": weights_path.as_posix(),
                "detections": detections,
            },
            indent=2,
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    print(f"Wrote prediction JSON: {output_path}")
    print(f"Detections: {len(detections)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
