from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


ZONE_CLASS_MAP: dict[str, str] = {
    "neck_label_area": "neck_label",
    "button_placket": "button_placket",
    "chest_pocket": "pocket",
    "left_pocket": "pocket",
    "right_pocket": "pocket",
    "kangaroo_pocket": "kangaroo_pocket",
    "chest_print_area": "chest_graphic",
    "collar": "collar",
    "neck_area": "collar",
    "left_cuff": "cuff",
    "right_cuff": "cuff",
    "hem": "hem_band",
    "left_hem": "hem_band",
    "right_hem": "hem_band",
    "hood": "hood",
    "waistband": "waistband",
    "fly_area": "zipper",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create starter YOLO labels from the local garment analysis templates."
    )
    parser.add_argument("--data", required=True, help="Path to dataset.yaml")
    parser.add_argument(
        "--config",
        default="config.DevConfig",
        help="Flask config object path for loading the app context.",
    )
    parser.add_argument(
        "--split",
        nargs="*",
        default=["train", "val"],
        help="Dataset splits to preannotate, for example train val.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite label files even if they already contain annotations.",
    )
    parser.add_argument(
        "--report",
        default="training/preannotation_report.json",
        help="Where to write the summary report JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_path = Path(args.data).resolve()
    if not data_path.exists():
        raise SystemExit(f"Dataset file not found: {data_path}")

    dataset = yaml.safe_load(data_path.read_text(encoding="utf-8")) or {}
    dataset_root = resolve_dataset_root(data_path, dataset)
    names = dataset.get("names") or {}
    class_map = build_class_map(names)
    if not class_map:
        raise SystemExit("No classes found in dataset.yaml names block.")

    from app import create_app
    from app.models import Product
    from app.services.garment_analysis_service import GarmentImageAnalysisService

    app = create_app(config_class=args.config)
    service = GarmentImageAnalysisService()

    with app.app_context():
        products = Product.query.all()
        product_index = build_product_index(products)
        report: dict[str, Any] = {
            "dataset_root": dataset_root.as_posix(),
            "splits": {},
            "supported_classes": sorted(class_map.keys()),
        }

        for split in args.split:
            split_report = preannotate_split(
                dataset_root=dataset_root,
                split=split,
                class_map=class_map,
                product_index=product_index,
                service=service,
                overwrite=args.overwrite,
            )
            report["splits"][split] = split_report

    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"Wrote report: {report_path}")
    for split, split_report in report["splits"].items():
        print(
            f"{split}: wrote={split_report['written']} skipped_existing={split_report['skipped_existing']} "
            f"unmatched={split_report['unmatched']} unsupported={split_report['unsupported']} "
            f"empty={split_report['empty']}"
        )
    return 0


def resolve_dataset_root(data_path: Path, dataset: dict[str, Any]) -> Path:
    root_value = str(dataset.get("path") or "").strip()
    if root_value:
        root_path = Path(root_value)
        if not root_path.is_absolute():
            root_path = (data_path.parent / root_path).resolve()
        return root_path
    return data_path.parent.resolve()


def build_class_map(names: Any) -> dict[str, int]:
    if isinstance(names, list):
        return {str(name): index for index, name in enumerate(names)}
    if isinstance(names, dict):
        result: dict[str, int] = {}
        for key, value in names.items():
            try:
                class_id = int(key)
            except (TypeError, ValueError):
                continue
            result[str(value)] = class_id
        return result
    return {}


def build_product_index(products: list[Any]) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for product in products:
        for raw in (getattr(product, "website_image", None), getattr(product, "image_path", None)):
            filename = extract_filename(raw)
            if filename and filename not in index:
                index[filename] = product
    return index


def extract_filename(raw: str | None) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    cleaned = value.replace("\\", "/").rstrip("/")
    if not cleaned:
        return None
    return cleaned.split("/")[-1] or None


def preannotate_split(
    *,
    dataset_root: Path,
    split: str,
    class_map: dict[str, int],
    product_index: dict[str, Any],
    service,
    overwrite: bool,
) -> dict[str, Any]:
    images_dir = dataset_root / "images" / split
    labels_dir = dataset_root / "labels" / split
    labels_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "images": 0,
        "written": 0,
        "skipped_existing": 0,
        "unmatched": 0,
        "unsupported": 0,
        "empty": 0,
        "files": [],
    }

    if not images_dir.exists():
        return report

    for image_path in sorted(path for path in images_dir.iterdir() if path.is_file()):
        report["images"] += 1
        label_path = labels_dir / f"{image_path.stem}.txt"
        existing = label_path.read_text(encoding="utf-8").strip() if label_path.exists() else ""
        if existing and not overwrite:
            report["skipped_existing"] += 1
            report["files"].append({"image": image_path.name, "status": "skipped_existing"})
            continue

        product = product_index.get(image_path.name)
        if not product:
            report["unmatched"] += 1
            report["files"].append({"image": image_path.name, "status": "unmatched_product"})
            continue

        category_key = service.normalize_category(getattr(product, "category", None))
        if not category_key:
            report["unsupported"] += 1
            report["files"].append({"image": image_path.name, "status": "unsupported_category"})
            continue

        analysis = service._analyze_image(
            image_path=image_path,
            source_image=image_path.name,
            category_key=category_key,
        )
        rows = build_label_rows(
            detections=analysis.get("detections") or [],
            class_map=class_map,
            image_width=int(analysis["image_size"]["width"]),
            image_height=int(analysis["image_size"]["height"]),
            category_key=category_key,
        )
        label_path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")

        status = "written" if rows else "empty"
        report[status] += 1
        report["files"].append(
            {
                "image": image_path.name,
                "status": status,
                "product_id": getattr(product, "id", None),
                "category": category_key,
                "rows": len(rows),
            }
        )

    return report


def build_label_rows(
    *,
    detections: list[dict[str, Any]],
    class_map: dict[str, int],
    image_width: int,
    image_height: int,
    category_key: str,
) -> list[str]:
    rows: list[str] = []
    for detection in detections:
        zone_key = str(detection.get("key") or "").strip()
        box = detection.get("box") or {}
        if not box:
            continue

        class_name = ZONE_CLASS_MAP.get(zone_key)
        if class_name in class_map:
            rows.append(box_to_yolo_line(box, class_map[class_name], image_width, image_height))

        if zone_key == "button_placket" and "button" in class_map:
            rows.extend(
                box_to_yolo_line(candidate, class_map["button"], image_width, image_height)
                for candidate in synthesize_button_boxes(box, category_key)
            )

        if zone_key in {"drawstrings_area", "hood"}:
            if "drawcord" in class_map:
                rows.extend(
                    box_to_yolo_line(candidate, class_map["drawcord"], image_width, image_height)
                    for candidate in synthesize_drawcord_boxes(box)
                )
            if "eyelet" in class_map:
                rows.extend(
                    box_to_yolo_line(candidate, class_map["eyelet"], image_width, image_height)
                    for candidate in synthesize_eyelet_boxes(box)
                )

        if zone_key == "fly_area" and "button" in class_map:
            top_button = synthesize_top_button_box(box)
            rows.append(box_to_yolo_line(top_button, class_map["button"], image_width, image_height))

    return dedupe_rows(rows)


def synthesize_button_boxes(box: dict[str, Any], category_key: str) -> list[dict[str, int]]:
    x = int(box.get("x", 0))
    y = int(box.get("y", 0))
    width = max(1, int(box.get("width", 0)))
    height = max(1, int(box.get("height", 0)))

    count = 4 if category_key == "shirt" else 3
    size = max(10, min(width, height // max(count, 1), int(width * 0.48)))
    x_center = x + width // 2
    left = x_center - size // 2
    top_margin = int(height * 0.18)
    bottom_margin = int(height * 0.16)
    usable_height = max(size, height - top_margin - bottom_margin)

    buttons: list[dict[str, int]] = []
    for index in range(count):
        center_y = y + top_margin + int((index + 0.5) * usable_height / count)
        buttons.append(
            {
                "x": left,
                "y": center_y - size // 2,
                "width": size,
                "height": size,
            }
        )
    return buttons


def synthesize_drawcord_boxes(box: dict[str, Any]) -> list[dict[str, int]]:
    x = int(box.get("x", 0))
    y = int(box.get("y", 0))
    width = max(1, int(box.get("width", 0)))
    height = max(1, int(box.get("height", 0)))
    cord_width = max(8, int(width * 0.14))
    cord_height = max(18, int(height * 0.74))
    top = y + int(height * 0.18)

    return [
        {
            "x": x + int(width * 0.23) - cord_width // 2,
            "y": top,
            "width": cord_width,
            "height": cord_height,
        },
        {
            "x": x + int(width * 0.77) - cord_width // 2,
            "y": top,
            "width": cord_width,
            "height": cord_height,
        },
    ]


def synthesize_eyelet_boxes(box: dict[str, Any]) -> list[dict[str, int]]:
    x = int(box.get("x", 0))
    y = int(box.get("y", 0))
    width = max(1, int(box.get("width", 0)))
    height = max(1, int(box.get("height", 0)))
    size = max(8, min(int(width * 0.14), int(height * 0.2)))
    top = y + int(height * 0.1)

    return [
        {
            "x": x + int(width * 0.28) - size // 2,
            "y": top,
            "width": size,
            "height": size,
        },
        {
            "x": x + int(width * 0.72) - size // 2,
            "y": top,
            "width": size,
            "height": size,
        },
    ]


def synthesize_top_button_box(box: dict[str, Any]) -> dict[str, int]:
    x = int(box.get("x", 0))
    y = int(box.get("y", 0))
    width = max(1, int(box.get("width", 0)))
    height = max(1, int(box.get("height", 0)))
    size = max(10, min(width, int(height * 0.2)))
    return {
        "x": x + width // 2 - size // 2,
        "y": y + int(height * 0.08),
        "width": size,
        "height": size,
    }


def box_to_yolo_line(
    box: dict[str, Any],
    class_id: int,
    image_width: int,
    image_height: int,
) -> str:
    x = float(box.get("x", 0))
    y = float(box.get("y", 0))
    width = max(1.0, float(box.get("width", 0)))
    height = max(1.0, float(box.get("height", 0)))
    x_center = (x + width / 2.0) / max(1.0, float(image_width))
    y_center = (y + height / 2.0) / max(1.0, float(image_height))
    width_norm = width / max(1.0, float(image_width))
    height_norm = height / max(1.0, float(image_height))
    return (
        f"{class_id} "
        f"{clamp01(x_center):.6f} "
        f"{clamp01(y_center):.6f} "
        f"{clamp01(width_norm):.6f} "
        f"{clamp01(height_norm):.6f}"
    )


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def dedupe_rows(rows: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row in seen:
            continue
        seen.add(row)
        unique.append(row)
    return unique


if __name__ == "__main__":
    raise SystemExit(main())
