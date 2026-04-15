from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path


DEFAULT_CLASSES = [
    "neck_label",
    "button",
    "button_placket",
    "zipper",
    "drawcord",
    "eyelet",
    "pocket",
    "kangaroo_pocket",
    "chest_graphic",
    "embroidery_patch",
    "collar",
    "cuff",
    "hem_band",
    "hood",
    "waistband",
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a YOLO-style garment dataset skeleton.")
    parser.add_argument("--source", required=True, help="Source directory with raw images.")
    parser.add_argument("--output", required=True, help="Output dataset root.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for split generation.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Train split ratio.")
    parser.add_argument("--val-ratio", type=float, default=0.2, help="Validation split ratio.")
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy images instead of hard-linking. Use this if links are not supported.",
    )
    parser.add_argument(
        "--classes",
        nargs="*",
        default=DEFAULT_CLASSES,
        help="Class list to write into dataset.yaml.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_dir = Path(args.source).resolve()
    output_dir = Path(args.output).resolve()

    if not source_dir.exists() or not source_dir.is_dir():
        raise SystemExit(f"Source directory not found: {source_dir}")

    images = sorted(
        path for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        raise SystemExit(f"No images found in {source_dir}")

    random.seed(args.seed)
    random.shuffle(images)

    train_count = int(len(images) * args.train_ratio)
    train_images = images[:train_count]
    val_images = images[train_count:]

    if not val_images:
        val_images = train_images[-1:]
        train_images = train_images[:-1]

    for split in ("train", "val"):
        (output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    for split_name, split_images in (("train", train_images), ("val", val_images)):
        for source_path in split_images:
            target_image = output_dir / "images" / split_name / source_path.name
            target_label = output_dir / "labels" / split_name / (source_path.stem + ".txt")

            if target_image.exists():
                target_image.unlink()

            if args.copy:
                shutil.copy2(source_path, target_image)
            else:
                try:
                    target_image.hardlink_to(source_path)
                except OSError:
                    shutil.copy2(source_path, target_image)

            target_label.touch(exist_ok=True)

    dataset_yaml = output_dir / "dataset.yaml"
    dataset_yaml.write_text(build_dataset_yaml(output_dir, args.classes), encoding="utf-8")

    readme = output_dir / "README.txt"
    readme.write_text(
        "\n".join(
            [
                "Garment detector dataset scaffold created.",
                "",
                "Next steps:",
                "1. Open images and labels in your annotation tool.",
                "2. Draw YOLO boxes for the classes in dataset.yaml.",
                "3. Train with scripts/train_garment_detector.py.",
            ]
        ),
        encoding="utf-8",
    )

    print(f"Prepared dataset in: {output_dir}")
    print(f"Train images: {len(train_images)}")
    print(f"Val images: {len(val_images)}")
    print(f"Classes: {', '.join(args.classes)}")
    return 0


def build_dataset_yaml(output_dir: Path, classes: list[str]) -> str:
    names_block = "\n".join(f"  {index}: {name}" for index, name in enumerate(classes))
    return (
        f"path: {output_dir.as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        f"nc: {len(classes)}\n"
        "names:\n"
        f"{names_block}\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
