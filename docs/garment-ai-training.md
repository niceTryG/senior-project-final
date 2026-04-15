# Garment AI Training Plan

This project now has a working manager-facing visual BOM layer in the Flask app.
The next step is replacing more of the hardcoded geometry with a trained detector.

## Approximate cost

Cheap local/open-source path:

- Annotation only, if you do it yourself:
  - 300 to 800 images: mostly time cost
  - Expect 8 to 30 hours depending on class count and annotation quality
- Electricity for local training:
  - Usually negligible compared to labor
  - Roughly under $5 to $20 for repeated experiments on a home GPU
- Cloud GPU rental instead of local GPU:
  - Roughly $0.35 to $1.50 per hour for common single-GPU rentals
  - A few experiments often land around $10 to $60 total
- Paid annotation help:
  - Small starter dataset: roughly $50 to $300
  - Better curated dataset with masks and QA: can easily grow beyond that

Realistic MVP estimate:

- If you already have a decent NVIDIA GPU and annotate yourself:
  - cash cost: about $0 to $20
  - real cost: your time
- If you rent GPU sometimes and annotate yourself:
  - about $15 to $80
- If you outsource annotation plus use occasional cloud training:
  - about $100 to $500 for a solid first pass

## What to train first

Do not train business outputs like `left_sleeve` and `right_sleeve` as the main final product view.
Train atomic visual things, then normalize them in the app.

Recommended first classes:

- `neck_label`
- `button`
- `button_placket`
- `zipper`
- `drawcord`
- `eyelet`
- `pocket`
- `kangaroo_pocket`
- `chest_graphic`
- `embroidery_patch`
- `collar`
- `cuff`
- `hem_band`
- `hood`
- `waistband`

Optional region classes for later:

- `body_panel`
- `sleeve_panel`
- `lining_panel`
- `contrast_panel`

## Why this class strategy is better

- Small objects like buttons and labels need direct supervision
- Structural pieces like sleeves can be merged later into one manager-facing component
- The Flask app already has a normalized component layer, so the detector should focus on visual evidence

## Suggested model path

Start simple:

1. YOLO detection for small and medium garment components
2. Later add segmentation for cleaner visual overlays
3. Keep the Flask visual BOM layer as the business-facing output

## Local training files in this repo

- Dataset prep: `scripts/prepare_garment_dataset.py`
- Train wrapper: `scripts/train_garment_detector.py`
- Predict wrapper: `scripts/predict_garment_detector.py`
- Optional training dependencies: `requirements-garment-ai.txt`

## Typical workflow

1. Collect images into a source directory
2. Run dataset prep
3. Optionally prefill starter labels from the current Flask garment analyzer
4. Review and correct labels in CVAT, Label Studio, or Roboflow export
5. Train a YOLO model locally
6. Run prediction on sample product images
7. Convert predictions into the Flask garment analysis pipeline later

## Example commands

```powershell
.\venv\Scripts\python scripts\prepare_garment_dataset.py `
  --source app\static\uploads\products `
  --output training\garment_dataset `
  --copy
```

```powershell
.\venv\Scripts\python scripts\preannotate_garment_dataset.py `
  --data training\garment_dataset\dataset.yaml
```

```powershell
.\venv\Scripts\python -m pip install -r requirements-garment-ai.txt
```

```powershell
.\venv\Scripts\python scripts\train_garment_detector.py `
  --data training\garment_dataset\dataset.yaml `
  --model yolo11n.pt `
  --imgsz 960 `
  --epochs 80
```

```powershell
.\venv\Scripts\python scripts\predict_garment_detector.py `
  --weights runs\detect\train\weights\best.pt `
  --image app\static\uploads\products\example.png `
  --output training\predictions\example.json
```

## Practical note about buttons

Buttons are small-object detection.
To improve button results:

- keep images high resolution
- use `imgsz` 960 or 1280 if your GPU allows it
- label many button examples
- include negative examples
- include different fabric/button contrast levels
- do not resize training images too aggressively

The preannotation script can create rough starter `button` boxes from a detected placket or fly area.
These are only bootstrap hints. They still need human correction before serious training.

## Integration direction

Once predictions are good enough, the app should:

1. run the trained detector
2. normalize detections into business components like `Sleeves`, `Neck label`, `Closure`
3. feed those into the existing mapping UI and visual BOM renderer
