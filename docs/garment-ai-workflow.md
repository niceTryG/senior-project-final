# Garment AI Workflow

This project now supports two garment-detail analysis modes:

- YOLO inference from trained weights when `best.pt` is available.
- Template fallback when no trained weights are present.

## What the app can detect well

Best visual targets:

- `button`
- `neck_label`
- `zipper`
- `pocket`
- `kangaroo_pocket`
- `collar`
- `cuff`
- `hood`
- `waistband`
- `chest_graphic`
- `embroidery_patch`

Still weak from a single product photo:

- thread color unless the photo is close and sharp
- material type without a second classifier or manual metadata
- packaging unless the packaging is visible in the image

## Train In Google Colab

1. Upload or mount this repo in Colab.
2. Install the garment AI dependencies:

```bash
pip install -r requirements-garment-ai.txt
```

3. Train from the dataset scaffold:

```bash
python scripts/train_garment_detector.py --data training/garment_dataset/dataset.yaml --model yolo11n.pt --epochs 80 --imgsz 960 --batch 8 --device 0
```

4. After training, download the weights file:

```text
runs/detect/garment_parts/weights/best.pt
```

## Connect Colab Weights Back To The App

Default location:

```text
training/weights/best.pt
```

You can also override it with an environment variable:

```text
GARMENT_AI_WEIGHTS=path/to/best.pt
```

Optional runtime settings:

```text
GARMENT_AI_DEVICE=cpu
GARMENT_AI_CONFIDENCE=0.25
```

## How It Works In The App

Once `best.pt` is present:

- product detail analysis will use YOLO first
- unsupported product categories can still be analyzed if YOLO detects visible parts
- repeated detections like multiple buttons are stored as separate zones
- if YOLO weights are missing, the previous template detector still runs

Use the existing product detail page action:

- open a product
- go to the garment map section
- click `Generate map` or `Rebuild map`

## Recommended Next Dataset Upgrade

Before serious training, improve the dataset by:

- removing non-garment images
- adding more real product photos from your own catalog
- manually correcting labels in an annotation tool
- making sure train and val contain the same class families
- getting at least 50 to 100 labeled examples per important class
