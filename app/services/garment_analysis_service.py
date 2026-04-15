from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from flask import current_app
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

from ..extensions import db
from ..models import Fabric, ProductComposition, ProductGarmentZoneAssignment


GARMENT_CATEGORY_ALIASES: dict[str, str] = {
    "t shirt": "t_shirt",
    "t-shirt": "t_shirt",
    "tshirt": "t_shirt",
    "tee": "t_shirt",
    "tee shirt": "t_shirt",
    "shirt": "shirt",
    "button shirt": "shirt",
    "dress shirt": "shirt",
    "hoodie": "hoodie",
    "hooded sweatshirt": "hoodie",
    "sweatshirt hoodie": "hoodie",
    "pants": "pants",
    "trousers": "pants",
    "jeans": "pants",
    "joggers": "pants",
}


GARMENT_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "t_shirt": [
        {"key": "neck_area", "label": "Neck area", "x": 0.5, "y": 0.13, "w": 0.28, "h": 0.11},
        {"key": "left_sleeve", "label": "Left sleeve", "x": 0.15, "y": 0.24, "w": 0.18, "h": 0.15},
        {"key": "right_sleeve", "label": "Right sleeve", "x": 0.85, "y": 0.24, "w": 0.18, "h": 0.15},
        {"key": "chest_print_area", "label": "Chest print area", "x": 0.5, "y": 0.39, "w": 0.36, "h": 0.2},
        {"key": "neck_label_area", "label": "Neck label area", "x": 0.5, "y": 0.055, "w": 0.11, "h": 0.045},
        {"key": "hem", "label": "Hem", "x": 0.5, "y": 0.93, "w": 0.48, "h": 0.08},
    ],
    "shirt": [
        {"key": "collar", "label": "Collar", "x": 0.5, "y": 0.11, "w": 0.34, "h": 0.12},
        {"key": "button_placket", "label": "Button placket", "x": 0.5, "y": 0.42, "w": 0.12, "h": 0.44},
        {"key": "left_cuff", "label": "Left cuff", "x": 0.14, "y": 0.7, "w": 0.14, "h": 0.11},
        {"key": "right_cuff", "label": "Right cuff", "x": 0.86, "y": 0.7, "w": 0.14, "h": 0.11},
        {"key": "chest_pocket", "label": "Chest pocket", "x": 0.33, "y": 0.34, "w": 0.17, "h": 0.14},
        {"key": "hem", "label": "Hem", "x": 0.5, "y": 0.93, "w": 0.48, "h": 0.08},
        {"key": "neck_label_area", "label": "Neck label area", "x": 0.5, "y": 0.05, "w": 0.11, "h": 0.042},
    ],
    "hoodie": [
        {"key": "hood", "label": "Hood", "x": 0.5, "y": 0.13, "w": 0.46, "h": 0.22},
        {"key": "drawstrings_area", "label": "Drawstrings area", "x": 0.5, "y": 0.24, "w": 0.16, "h": 0.14},
        {"key": "kangaroo_pocket", "label": "Kangaroo pocket", "x": 0.5, "y": 0.59, "w": 0.44, "h": 0.18},
        {"key": "left_cuff", "label": "Left cuff", "x": 0.14, "y": 0.74, "w": 0.13, "h": 0.11},
        {"key": "right_cuff", "label": "Right cuff", "x": 0.86, "y": 0.74, "w": 0.13, "h": 0.11},
        {"key": "hem", "label": "Hem", "x": 0.5, "y": 0.93, "w": 0.5, "h": 0.08},
    ],
    "pants": [
        {"key": "waistband", "label": "Waistband", "x": 0.5, "y": 0.08, "w": 0.58, "h": 0.1},
        {"key": "fly_area", "label": "Fly area", "x": 0.5, "y": 0.25, "w": 0.16, "h": 0.18},
        {"key": "left_pocket", "label": "Left pocket", "x": 0.29, "y": 0.18, "w": 0.18, "h": 0.14},
        {"key": "right_pocket", "label": "Right pocket", "x": 0.71, "y": 0.18, "w": 0.18, "h": 0.14},
        {"key": "left_hem", "label": "Left hem", "x": 0.33, "y": 0.93, "w": 0.18, "h": 0.08},
        {"key": "right_hem", "label": "Right hem", "x": 0.67, "y": 0.93, "w": 0.18, "h": 0.08},
    ],
}


ZONE_PROFILES: dict[str, dict[str, Any]] = {
    "neck_area": {
        "usage_label": "Neck binding / collar rib",
        "preferred_material_types": ["fabric", "accessory", "thread"],
        "keywords": ["rib", "collar", "binding", "neck", "tape"],
        "detail_roles": ["Main fabric", "Rib collar", "Binding tape", "Topstitch thread"],
    },
    "neck_label_area": {
        "usage_label": "Brand / size label",
        "preferred_material_types": ["label", "accessory", "packaging"],
        "keywords": ["label", "tag", "neck", "size", "brand", "care"],
        "detail_roles": ["Brand label", "Size label", "Care label", "Heat transfer label"],
    },
    "left_sleeve": {
        "usage_label": "Sleeve panel or trim",
        "preferred_material_types": ["fabric", "accessory", "thread"],
        "keywords": ["sleeve", "fabric", "cuff", "trim", "panel"],
        "detail_roles": ["Main fabric", "Contrast fabric", "Sleeve trim", "Embroidery"],
    },
    "right_sleeve": {
        "usage_label": "Sleeve panel or trim",
        "preferred_material_types": ["fabric", "accessory", "thread"],
        "keywords": ["sleeve", "fabric", "cuff", "trim", "panel"],
        "detail_roles": ["Main fabric", "Contrast fabric", "Sleeve trim", "Patch"],
    },
    "chest_print_area": {
        "usage_label": "Graphic / embroidery / pocket area",
        "preferred_material_types": ["accessory", "label", "fabric", "thread", "other"],
        "keywords": ["print", "logo", "graphic", "embroidery", "patch", "pocket", "vinyl", "screen"],
        "detail_roles": ["Print", "Embroidery", "Patch", "Pocket", "Heat transfer"],
    },
    "collar": {
        "usage_label": "Collar construction",
        "preferred_material_types": ["fabric", "accessory", "thread"],
        "keywords": ["collar", "rib", "fabric", "interfacing"],
        "detail_roles": ["Main collar fabric", "Rib collar", "Interfacing", "Topstitch thread"],
    },
    "button_placket": {
        "usage_label": "Closure and placket",
        "preferred_material_types": ["button", "fabric", "thread", "accessory"],
        "keywords": ["button", "placket", "closure", "snap", "zipper"],
        "detail_roles": ["Buttons", "Placket fabric", "Snap buttons", "Zipper"],
    },
    "left_cuff": {
        "usage_label": "Cuff finish",
        "preferred_material_types": ["fabric", "button", "accessory", "thread"],
        "keywords": ["cuff", "rib", "button", "snap", "trim"],
        "detail_roles": ["Cuff fabric", "Rib cuff", "Button cuff", "Trim"],
    },
    "right_cuff": {
        "usage_label": "Cuff finish",
        "preferred_material_types": ["fabric", "button", "accessory", "thread"],
        "keywords": ["cuff", "rib", "button", "snap", "trim"],
        "detail_roles": ["Cuff fabric", "Rib cuff", "Button cuff", "Trim"],
    },
    "chest_pocket": {
        "usage_label": "Pocket component",
        "preferred_material_types": ["fabric", "accessory", "thread", "button"],
        "keywords": ["pocket", "patch", "welt", "button"],
        "detail_roles": ["Pocket fabric", "Pocket flap", "Decorative button", "Embroidery"],
    },
    "hood": {
        "usage_label": "Hood shell / lining",
        "preferred_material_types": ["fabric", "thread", "accessory"],
        "keywords": ["hood", "lining", "shell", "panel"],
        "detail_roles": ["Hood fabric", "Hood lining", "Topstitch thread", "Contrast panel"],
    },
    "drawstrings_area": {
        "usage_label": "Drawcord system",
        "preferred_material_types": ["accessory", "label", "thread", "other"],
        "keywords": ["drawstring", "cord", "grommet", "eyelet", "toggle"],
        "detail_roles": ["Drawcord", "Eyelet", "Cord stopper", "Heat transfer branding"],
    },
    "kangaroo_pocket": {
        "usage_label": "Pocket structure",
        "preferred_material_types": ["fabric", "thread", "accessory"],
        "keywords": ["pocket", "kangaroo", "patch", "zip"],
        "detail_roles": ["Pocket fabric", "Pocket lining", "Zipper", "Topstitch thread"],
    },
    "waistband": {
        "usage_label": "Waist finish",
        "preferred_material_types": ["fabric", "accessory", "thread", "label"],
        "keywords": ["waist", "elastic", "band", "drawstring", "label"],
        "detail_roles": ["Waistband fabric", "Elastic", "Drawcord", "Waist label"],
    },
    "fly_area": {
        "usage_label": "Fly closure",
        "preferred_material_types": ["zipper", "button", "fabric", "thread", "accessory"],
        "keywords": ["fly", "zip", "zipper", "button", "snap"],
        "detail_roles": ["Zipper", "Fly button", "Fly fabric", "Reinforcement"],
    },
    "left_pocket": {
        "usage_label": "Pocket component",
        "preferred_material_types": ["fabric", "thread", "accessory"],
        "keywords": ["pocket", "lining", "zip", "welt"],
        "detail_roles": ["Pocket bag", "Pocket opening", "Zipper pocket", "Topstitch thread"],
    },
    "right_pocket": {
        "usage_label": "Pocket component",
        "preferred_material_types": ["fabric", "thread", "accessory"],
        "keywords": ["pocket", "lining", "zip", "welt"],
        "detail_roles": ["Pocket bag", "Pocket opening", "Zipper pocket", "Topstitch thread"],
    },
    "hem": {
        "usage_label": "Hem finish",
        "preferred_material_types": ["fabric", "accessory", "thread"],
        "keywords": ["hem", "rib", "binding", "tape", "thread"],
        "detail_roles": ["Main fabric", "Hem rib", "Binding tape", "Topstitch thread"],
    },
    "left_hem": {
        "usage_label": "Hem finish",
        "preferred_material_types": ["fabric", "accessory", "thread"],
        "keywords": ["hem", "rib", "binding", "tape", "thread"],
        "detail_roles": ["Main fabric", "Hem rib", "Binding tape", "Topstitch thread"],
    },
    "right_hem": {
        "usage_label": "Hem finish",
        "preferred_material_types": ["fabric", "accessory", "thread"],
        "keywords": ["hem", "rib", "binding", "tape", "thread"],
        "detail_roles": ["Main fabric", "Hem rib", "Binding tape", "Topstitch thread"],
    },
}


COMPONENT_GROUPS: dict[str, dict[str, Any]] = {
    "neck": {
        "label": "Neck / collar",
        "zone_keys": ["neck_area", "collar"],
        "description": "Main neckline construction, collar fabric, rib, binding, or interfacing.",
    },
    "neck_label": {
        "label": "Neck label",
        "zone_keys": ["neck_label_area", "neck_label"],
        "description": "Brand, size, care, and heat-transfer labels placed inside the neck.",
    },
    "sleeves": {
        "label": "Sleeves",
        "zone_keys": ["left_sleeve", "right_sleeve"],
        "description": "Use one mapping when both sleeves share the same fabric or trim.",
    },
    "cuffs": {
        "label": "Cuffs",
        "zone_keys": ["left_cuff", "right_cuff", "cuff"],
        "description": "Cuff finishing, rib, button, or trim details.",
    },
    "decoration": {
        "label": "Front decoration",
        "zone_keys": ["chest_print_area", "chest_graphic", "embroidery_patch"],
        "description": "Print, embroidery, patch, appliqué, or branding placement.",
    },
    "closure": {
        "label": "Closure",
        "zone_keys": ["button_placket", "fly_area", "drawstrings_area", "button", "zipper", "drawcord", "eyelet"],
        "description": "Buttons, zipper, drawcord systems, snaps, and closure hardware.",
    },
    "pocket": {
        "label": "Pocket",
        "zone_keys": ["chest_pocket", "kangaroo_pocket", "left_pocket", "right_pocket", "pocket"],
        "description": "Pocket structures, pocket bags, pocket trims, and zipper pockets.",
    },
    "hood": {
        "label": "Hood",
        "zone_keys": ["hood"],
        "description": "Hood shell, lining, and hood-specific trims.",
    },
    "waist": {
        "label": "Waist / waistband",
        "zone_keys": ["waistband"],
        "description": "Waistband fabric, elastic, drawcord, and waist labels.",
    },
    "hem_finish": {
        "label": "Hem finish",
        "zone_keys": ["hem", "left_hem", "right_hem", "hem_band"],
        "description": "Bottom hem, rib, binding tape, and finishing thread.",
    },
}


YOLO_CLASS_ZONE_KEYS: dict[str, str] = {
    "neck_label": "neck_label",
    "button": "button",
    "button_placket": "button_placket",
    "zipper": "zipper",
    "drawcord": "drawcord",
    "eyelet": "eyelet",
    "pocket": "pocket",
    "kangaroo_pocket": "kangaroo_pocket",
    "chest_graphic": "chest_graphic",
    "embroidery_patch": "embroidery_patch",
    "collar": "collar",
    "cuff": "cuff",
    "hem_band": "hem_band",
    "hood": "hood",
    "waistband": "waistband",
}


YOLO_CLASS_LABELS: dict[str, str] = {
    "neck_label": "Neck label",
    "button": "Button",
    "button_placket": "Button placket",
    "zipper": "Zipper",
    "drawcord": "Drawcord",
    "eyelet": "Eyelet",
    "pocket": "Pocket",
    "kangaroo_pocket": "Kangaroo pocket",
    "chest_graphic": "Chest graphic",
    "embroidery_patch": "Embroidery patch",
    "collar": "Collar",
    "cuff": "Cuff",
    "hem_band": "Hem band",
    "hood": "Hood",
    "waistband": "Waistband",
}


class GarmentImageAnalysisService:
    DETECTOR_VERSION = "template-silhouette-v1"
    SCHEMA_VERSION = 1

    def normalize_category(self, category: str | None) -> str | None:
        raw = (category or "").strip().lower().replace("-", " ").replace("_", " ")
        raw = " ".join(raw.split())
        if not raw:
            return None
        if raw in GARMENT_TEMPLATES:
            return raw
        return GARMENT_CATEGORY_ALIASES.get(raw)

    def supports_category(self, category: str | None) -> bool:
        return self.normalize_category(category) is not None or self._yolo_detector_ready()

    def analyze_and_store(self, product, *, commit: bool = True) -> dict[str, Any]:
        category_key = self.normalize_category(getattr(product, "category", None))
        source_image = self._select_source_image(product)
        yolo_ready = self._yolo_detector_ready()

        if not category_key and not yolo_ready:
            self.clear_analysis(product, reason="unsupported_category", commit=commit)
            return {"status": "skipped", "reason": "unsupported_category"}

        if not source_image:
            self.clear_analysis(product, reason="missing_image", commit=commit)
            return {"status": "skipped", "reason": "missing_image"}

        image_path = self._resolve_image_path(source_image)
        if not image_path.exists():
            self.clear_analysis(product, reason="missing_source_file", commit=commit)
            return {"status": "skipped", "reason": "missing_source_file"}

        analysis = self._analyze_image(
            image_path=image_path,
            source_image=source_image,
            category_key=category_key,
        )
        annotation_image = self._save_annotation_image(product, image_path, analysis)

        product.garment_analysis_json = json.dumps(analysis, ensure_ascii=True)
        product.garment_annotation_image = annotation_image
        product.garment_analysis_version = str(analysis.get("detector") or self.DETECTOR_VERSION)
        product.garment_analysis_updated_at = datetime.utcnow()

        if commit:
            db.session.commit()

        return {
            "status": "analyzed",
            "detail_count": len(analysis.get("detections") or []),
            "annotation_image": annotation_image,
        }

    def rebuild_annotation_from_saved_analysis(self, product, *, commit: bool = True) -> str | None:
        analysis = self.get_analysis_payload(product)
        source_image = self._select_source_image(product)
        if not analysis or not source_image:
            return None

        image_path = self._resolve_image_path(source_image)
        if not image_path.exists():
            return None

        annotation_image = self._save_annotation_image(product, image_path, analysis)
        product.garment_annotation_image = annotation_image
        product.garment_analysis_updated_at = datetime.utcnow()
        if commit:
            db.session.commit()
        return annotation_image

    def clear_analysis(self, product, *, reason: str | None = None, commit: bool = True) -> None:
        old_annotation = getattr(product, "garment_annotation_image", None)
        product.garment_analysis_json = None
        product.garment_annotation_image = None
        product.garment_analysis_version = None
        product.garment_analysis_updated_at = None
        if old_annotation:
            self._remove_annotation_file(old_annotation)
        if commit:
            db.session.commit()

    def get_analysis_payload(self, product) -> dict[str, Any] | None:
        raw = getattr(product, "garment_analysis_json", None)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def build_view_model(self, product) -> dict[str, Any]:
        payload = self.get_analysis_payload(product) or {}
        detections = payload.get("detections") or []
        category_key = self.normalize_category(getattr(product, "category", None))
        source_image = self._select_source_image(product)

        return {
            "supported_category": bool(category_key) or self._yolo_detector_ready(),
            "category_key": category_key,
            "has_source_image": bool(source_image),
            "source_image": source_image,
            "annotated_image": getattr(product, "garment_annotation_image", None),
            "has_analysis": bool(detections),
            "detections": detections,
            "detail_count": len(detections),
            "generated_at": payload.get("generated_at"),
            "detector_version": getattr(product, "garment_analysis_version", None) or payload.get("detector"),
            "foreground_bbox": payload.get("foreground_bbox"),
            "detector_ready": self._yolo_detector_ready(),
        }

    def build_mapping_view_model(self, product, *, factory_id: int | None = None) -> dict[str, Any]:
        analysis = self.build_view_model(product)
        detections = analysis.get("detections") or []

        composition_items = sorted(
            list(getattr(product, "composition_items", []) or []),
            key=lambda item: (
                str(getattr(getattr(item, "fabric", None), "material_type", "") or ""),
                str(getattr(getattr(item, "fabric", None), "name", "") or ""),
            ),
        )
        assignments = self._load_assignments_by_zone(getattr(product, "id", None))

        factory_materials = self._load_factory_materials(factory_id)
        mapped_count = 0
        enriched_zones: list[dict[str, Any]] = []

        for detection in detections:
            zone_key = str(detection.get("key") or "").strip()
            assignment = assignments.get(zone_key)
            zone = dict(detection)
            zone["profile"] = self._zone_profile(zone_key, detection.get("label"))
            zone["assignment"] = self._serialize_assignment(assignment)
            zone["candidate_groups"] = self._candidate_groups(
                zone_key=zone_key,
                composition_items=composition_items,
                factory_materials=factory_materials,
            )
            zone["usage_options"] = list(zone["profile"].get("detail_roles") or [])

            if assignment and assignment.assignment_kind != "unassigned":
                mapped_count += 1

            enriched_zones.append(zone)

        return {
            "zones": enriched_zones,
            "mapped_count": mapped_count,
            "unmapped_count": max(0, len(enriched_zones) - mapped_count),
            "composition_count": len(composition_items),
            "components": self._build_component_view_model(enriched_zones),
        }

    def save_zone_assignment(
        self,
        *,
        product,
        zone_key: str,
        zone_label: str,
        selection: str | None,
        usage_label: str | None,
        note: str | None,
    ) -> ProductGarmentZoneAssignment:
        zone_key_clean = str(zone_key or "").strip()
        zone_label_clean = str(zone_label or zone_key_clean).strip() or zone_key_clean
        selection_clean = str(selection or "").strip()

        assignment = ProductGarmentZoneAssignment.query.filter_by(
            product_id=product.id,
            zone_key=zone_key_clean,
        ).first()
        if not assignment:
            assignment = ProductGarmentZoneAssignment(
                product_id=product.id,
                zone_key=zone_key_clean,
                zone_label=zone_label_clean,
            )
            db.session.add(assignment)

        assignment.zone_label = zone_label_clean
        assignment.usage_label = str(usage_label or "").strip() or None
        assignment.note = str(note or "").strip() or None
        assignment.assignment_kind = "unassigned"
        assignment.product_composition_id = None
        assignment.fabric_id = None

        if selection_clean.startswith("comp:"):
            try:
                composition_id = int(selection_clean.split(":", 1)[1])
            except (TypeError, ValueError):
                composition_id = 0
            composition = ProductComposition.query.get(composition_id) if composition_id else None
            if composition:
                assignment.assignment_kind = "composition_item"
                assignment.product_composition_id = composition.id
                assignment.fabric_id = composition.fabric_id
        elif selection_clean.startswith("material:"):
            try:
                material_id = int(selection_clean.split(":", 1)[1])
            except (TypeError, ValueError):
                material_id = 0
            fabric = Fabric.query.get(material_id) if material_id else None
            if fabric:
                assignment.assignment_kind = "material"
                assignment.fabric_id = fabric.id
        elif selection_clean == "custom":
            assignment.assignment_kind = "custom"

        db.session.commit()
        self.rebuild_annotation_from_saved_analysis(product, commit=True)
        return assignment

    def save_component_assignment(
        self,
        *,
        product,
        component_key: str,
        selection: str | None,
        usage_label: str | None,
        note: str | None,
    ) -> dict[str, Any]:
        component = COMPONENT_GROUPS.get(component_key) or {}
        zone_keys = list(component.get("zone_keys") or [])
        updated = 0

        for zone_key in zone_keys:
            zone_label = self._zone_profile(zone_key).get("usage_label") or zone_key.replace("_", " ").title()
            self.save_zone_assignment(
                product=product,
                zone_key=zone_key,
                zone_label=str(zone_label),
                selection=selection,
                usage_label=usage_label,
                note=note,
            )
            updated += 1

        self.rebuild_annotation_from_saved_analysis(product, commit=True)
        return {"updated": updated, "component_key": component_key}

    def auto_map_zones(self, *, product, factory_id: int | None = None) -> dict[str, int]:
        mapping = self.build_mapping_view_model(product, factory_id=factory_id)
        updated = 0

        for zone in mapping.get("zones") or []:
            assignment = zone.get("assignment") or {}
            if assignment.get("kind") and assignment.get("kind") != "unassigned":
                continue

            candidate_groups = zone.get("candidate_groups") or []
            if not candidate_groups:
                continue

            top_group = candidate_groups[0]
            top_options = top_group.get("options") or []
            if not top_options:
                continue

            top_option = top_options[0]
            if int(top_option.get("score") or 0) < 45:
                continue

            self.save_zone_assignment(
                product=product,
                zone_key=str(zone.get("key") or ""),
                zone_label=str(zone.get("label") or zone.get("key") or ""),
                selection=str(top_option.get("value") or ""),
                usage_label=str(zone.get("profile", {}).get("usage_label") or zone.get("label") or ""),
                note="Auto-mapped from top recommendation",
            )
            updated += 1

        if updated:
            self.rebuild_annotation_from_saved_analysis(product, commit=True)

        return {"updated": updated, "total": len(mapping.get("zones") or [])}

    def auto_map_components(self, *, product, factory_id: int | None = None) -> dict[str, int]:
        mapping = self.build_mapping_view_model(product, factory_id=factory_id)
        updated = 0

        for component in mapping.get("components") or []:
            assignment = component.get("assignment") or {}
            if assignment.get("kind") and assignment.get("kind") != "unassigned":
                continue

            candidate_groups = component.get("candidate_groups") or []
            if not candidate_groups:
                continue

            top_options = candidate_groups[0].get("options") or []
            if not top_options:
                continue

            top_option = top_options[0]
            if int(top_option.get("score") or 0) < 45:
                continue

            self.save_component_assignment(
                product=product,
                component_key=str(component.get("key") or ""),
                selection=str(top_option.get("value") or ""),
                usage_label=str(component.get("usage_label") or component.get("label") or ""),
                note="Auto-mapped from top component recommendation",
            )
            updated += 1

        if updated:
            self.rebuild_annotation_from_saved_analysis(product, commit=True)

        return {"updated": updated, "total": len(mapping.get("components") or [])}

    def _select_source_image(self, product) -> str | None:
        for candidate in (getattr(product, "website_image", None), getattr(product, "image_path", None)):
            clean = str(candidate or "").strip()
            if clean:
                return clean
        return None

    def _resolve_yolo_weights_path(self) -> Path:
        raw = str(current_app.config.get("GARMENT_AI_WEIGHTS") or "").strip()
        if not raw:
            return Path(current_app.root_path).parent / "training" / "weights" / "best.pt"
        path = Path(raw).expanduser()
        if path.is_absolute():
            return path
        return Path(current_app.root_path).parent / path

    def _yolo_detector_ready(self) -> bool:
        weights_path = self._resolve_yolo_weights_path()
        return weights_path.exists() and weights_path.is_file()

    def _load_yolo_model(self):
        weights_path = self._resolve_yolo_weights_path()
        cache_key = "_garment_yolo_cache"
        cache = current_app.extensions.get(cache_key)
        if cache and cache.get("path") == str(weights_path) and cache.get("model") is not None:
            return cache["model"], weights_path

        try:
            from ultralytics import YOLO
        except ModuleNotFoundError:
            return None, weights_path

        if not weights_path.exists():
            return None, weights_path

        model = YOLO(str(weights_path))
        current_app.extensions[cache_key] = {"path": str(weights_path), "model": model}
        return model, weights_path

    def _resolve_upload_folder(self) -> Path:
        upload_folder = Path(str(current_app.config.get("UPLOAD_FOLDER") or "")).expanduser()
        if not upload_folder.is_absolute():
            upload_folder = Path(current_app.root_path).parent / upload_folder
        upload_folder.mkdir(parents=True, exist_ok=True)
        return upload_folder

    def _resolve_image_path(self, value: str) -> Path:
        raw = str(value or "").strip()
        upload_folder = self._resolve_upload_folder()
        static_folder = Path(current_app.static_folder)

        if raw.startswith("/uploads/"):
            return upload_folder / raw[len("/uploads/"):].lstrip("/\\")
        if raw.startswith("uploads/"):
            return static_folder / raw
        if raw.startswith("/static/"):
            return static_folder / raw[len("/static/"):].lstrip("/\\")
        if raw.startswith("/"):
            return Path(current_app.root_path).parent / raw.lstrip("/\\")
        return upload_folder / raw

    def _zone_profile(self, zone_key: str, fallback_label: str | None = None) -> dict[str, Any]:
        base_key = self._base_zone_key(zone_key)
        profile = dict(ZONE_PROFILES.get(zone_key, {}) or ZONE_PROFILES.get(base_key, {}))
        profile.setdefault("usage_label", str(fallback_label or base_key or zone_key).replace("_", " ").title())
        profile.setdefault("preferred_material_types", ["fabric", "accessory", "other"])
        profile.setdefault("keywords", [base_key.replace("_", " ") if base_key else zone_key.replace("_", " ")])
        profile.setdefault("detail_roles", [profile["usage_label"], "Main fabric", "Decoration", "Trim"])
        return profile

    def _load_factory_materials(self, factory_id: int | None) -> list[Fabric]:
        if not factory_id:
            return []
        return (
            Fabric.query
            .filter(Fabric.factory_id == factory_id)
            .order_by(Fabric.material_type.asc(), Fabric.name.asc())
            .limit(200)
            .all()
        )

    def _candidate_groups(
        self,
        *,
        zone_key: str,
        composition_items: list[ProductComposition],
        factory_materials: list[Fabric],
    ) -> list[dict[str, Any]]:
        composition_candidates = self._score_composition_candidates(zone_key, composition_items)
        candidate_material_ids = {
            int(candidate["fabric_id"])
            for candidate in composition_candidates
            if candidate.get("fabric_id") is not None
        }
        extra_material_candidates = self._score_material_candidates(
            zone_key,
            [
                material
                for material in factory_materials
                if int(getattr(material, "id", 0) or 0) not in candidate_material_ids
            ],
        )

        groups: list[dict[str, Any]] = []
        if composition_candidates:
            groups.append({"label": "Recommended from product composition", "options": composition_candidates[:8]})
        if extra_material_candidates:
            groups.append({"label": "Other matching factory materials", "options": extra_material_candidates[:10]})
        return groups

    def _build_component_view_model(self, zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
        components: list[dict[str, Any]] = []
        used_zone_keys: set[str] = set()

        for component_key, definition in COMPONENT_GROUPS.items():
            related_zones = [
                zone
                for zone in zones
                if self._base_zone_key(str(zone.get("key") or "")) in set(definition.get("zone_keys") or [])
            ]
            if not related_zones:
                continue

            assignments = [zone.get("assignment") for zone in related_zones if zone.get("assignment")]
            merged_assignment = self._merge_component_assignment(assignments)
            candidate_groups = self._merge_candidate_groups(
                [zone.get("candidate_groups") or [] for zone in related_zones]
            )
            avg_confidence = round(
                sum(float(zone.get("confidence") or 0) for zone in related_zones) / max(1, len(related_zones)),
                2,
            )

            usage_label = None
            if merged_assignment and merged_assignment.get("usage_label"):
                usage_label = merged_assignment.get("usage_label")
            else:
                usage_label = related_zones[0].get("profile", {}).get("usage_label") or definition.get("label")

            components.append(
                {
                    "key": component_key,
                    "label": definition.get("label"),
                    "description": definition.get("description"),
                    "zones": related_zones,
                    "zone_keys": [zone.get("key") for zone in related_zones],
                    "zone_labels": [zone.get("label") for zone in related_zones],
                    "zone_count": len(related_zones),
                    "assignment": merged_assignment,
                    "candidate_groups": candidate_groups,
                    "usage_options": self._merge_usage_options(related_zones),
                    "usage_label": usage_label,
                    "confidence": avg_confidence,
                    "symmetry_mode": "merged" if len(related_zones) > 1 else "single",
                }
            )
            used_zone_keys.update(str(zone.get("key") or "") for zone in related_zones)

        for zone in zones:
            zone_key = str(zone.get("key") or "")
            if not zone_key or zone_key in used_zone_keys:
                continue
            components.append(
                {
                    "key": zone_key,
                    "label": zone.get("label") or self._base_zone_key(zone_key).replace("_", " ").title(),
                    "description": "Detected garment detail awaiting mapping.",
                    "zones": [zone],
                    "zone_keys": [zone_key],
                    "zone_labels": [zone.get("label")],
                    "zone_count": 1,
                    "assignment": zone.get("assignment"),
                    "candidate_groups": zone.get("candidate_groups") or [],
                    "usage_options": zone.get("usage_options") or [],
                    "usage_label": (
                        ((zone.get("assignment") or {}).get("usage_label"))
                        or ((zone.get("profile") or {}).get("usage_label"))
                        or zone.get("label")
                    ),
                    "confidence": round(float(zone.get("confidence") or 0), 2),
                    "symmetry_mode": "single",
                }
            )

        return components

    def _base_zone_key(self, zone_key: str) -> str:
        clean = str(zone_key or "").strip()
        return re.sub(r"_\d+$", "", clean)

    def _merge_component_assignment(self, assignments: list[dict[str, Any] | None]) -> dict[str, Any] | None:
        clean = [assignment for assignment in assignments if assignment]
        if not clean:
            return None

        selection_values = {str(assignment.get("selection_value") or "") for assignment in clean}
        kinds = {str(assignment.get("kind") or "unassigned") for assignment in clean}

        first = dict(clean[0])
        if len(selection_values) == 1 and len(kinds) == 1:
            return first

        first["kind"] = "mixed"
        first["material_name"] = "Mixed zone assignments"
        first["overlay_text"] = None
        return first

    def _merge_candidate_groups(self, zone_groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}

        for groups in zone_groups:
            for group in groups:
                label = str(group.get("label") or "Suggestions")
                bucket = buckets.setdefault(label, {"label": label, "options": {}})
                for option in list(group.get("options") or []):
                    value = str(option.get("value") or "")
                    if not value:
                        continue
                    existing = bucket["options"].get(value)
                    if existing is None or int(option.get("score") or 0) > int(existing.get("score") or 0):
                        bucket["options"][value] = dict(option)

        merged_groups: list[dict[str, Any]] = []
        for bucket in buckets.values():
            options = sorted(
                bucket["options"].values(),
                key=lambda item: (-int(item.get("score") or 0), str(item.get("label") or "")),
            )
            if options:
                merged_groups.append({"label": bucket["label"], "options": options[:10]})
        return merged_groups

    def _merge_usage_options(self, zones: list[dict[str, Any]]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for zone in zones:
            for option in list(zone.get("usage_options") or []):
                clean = str(option or "").strip()
                if clean and clean not in seen:
                    seen.add(clean)
                    merged.append(clean)
        return merged

    def _score_composition_candidates(self, zone_key: str, items: list[ProductComposition]) -> list[dict[str, Any]]:
        profile = self._zone_profile(zone_key)
        candidates: list[dict[str, Any]] = []
        for item in items:
            fabric = getattr(item, "fabric", None)
            if not fabric:
                continue
            score = self._match_score(
                material_type=str(getattr(fabric, "material_type", "") or ""),
                text_parts=[
                    getattr(fabric, "name", ""),
                    getattr(fabric, "category", ""),
                    getattr(fabric, "public_id", ""),
                    getattr(item, "note", ""),
                    zone_key,
                ],
                profile=profile,
                composition_bonus=18,
            )
            candidates.append(
                {
                    "value": f"comp:{item.id}",
                    "label": self._composition_label(item),
                    "score": score,
                    "fabric_id": getattr(fabric, "id", None),
                    "badge": "In composition",
                }
            )
        return sorted(candidates, key=lambda item: (-int(item["score"]), str(item["label"])))

    def _score_material_candidates(self, zone_key: str, materials: list[Fabric]) -> list[dict[str, Any]]:
        profile = self._zone_profile(zone_key)
        candidates: list[dict[str, Any]] = []
        for fabric in materials:
            score = self._match_score(
                material_type=str(getattr(fabric, "material_type", "") or ""),
                text_parts=[
                    getattr(fabric, "name", ""),
                    getattr(fabric, "category", ""),
                    getattr(fabric, "public_id", ""),
                    getattr(fabric, "supplier_name", ""),
                    zone_key,
                ],
                profile=profile,
                composition_bonus=0,
            )
            if score < 15:
                continue
            candidates.append(
                {
                    "value": f"material:{fabric.id}",
                    "label": self._material_label(fabric),
                    "score": score,
                    "fabric_id": getattr(fabric, "id", None),
                    "badge": "Factory material",
                }
            )
        return sorted(candidates, key=lambda item: (-int(item["score"]), str(item["label"])))

    def _match_score(
        self,
        *,
        material_type: str,
        text_parts: list[Any],
        profile: dict[str, Any],
        composition_bonus: int,
    ) -> int:
        score = composition_bonus
        material_type_clean = str(material_type or "").strip().lower()
        preferred_types = [str(value).strip().lower() for value in list(profile.get("preferred_material_types") or [])]
        if material_type_clean in preferred_types:
            score += 40
            if preferred_types and material_type_clean == preferred_types[0]:
                score += 10

        haystack = " ".join(str(part or "").strip().lower() for part in text_parts)
        for keyword in list(profile.get("keywords") or []):
            keyword_clean = str(keyword or "").strip().lower()
            if keyword_clean and keyword_clean in haystack:
                score += 18

        for role in list(profile.get("detail_roles") or []):
            role_clean = str(role or "").strip().lower()
            if role_clean and role_clean in haystack:
                score += 12

        return score

    def _composition_label(self, item: ProductComposition) -> str:
        fabric = getattr(item, "fabric", None)
        material_name = getattr(fabric, "name", "Material")
        material_type = str(getattr(fabric, "material_type", "fabric") or "fabric").replace("_", " ").title()
        public_id = getattr(fabric, "public_id", None)
        qty = float(getattr(item, "quantity_required", 0) or 0)
        qty_text = f"{qty:g} {getattr(item, 'unit', '')}".strip()
        suffix = f" • {qty_text}" if qty_text else ""
        public = f"{public_id} • " if public_id else ""
        return f"{public}{material_type} • {material_name}{suffix}"

    def _material_label(self, fabric: Fabric) -> str:
        material_type = str(getattr(fabric, "material_type", "fabric") or "fabric").replace("_", " ").title()
        parts = [getattr(fabric, "public_id", None), material_type, getattr(fabric, "name", "Material")]
        if getattr(fabric, "category", None):
            parts.append(getattr(fabric, "category"))
        return " • ".join(str(part) for part in parts if part)

    def _serialize_assignment(self, assignment: ProductGarmentZoneAssignment | None) -> dict[str, Any] | None:
        if not assignment:
            return None

        material_name = None
        if assignment.product_composition and assignment.product_composition.fabric:
            material_name = self._composition_label(assignment.product_composition)
        elif assignment.fabric:
            material_name = self._material_label(assignment.fabric)

        return {
            "kind": assignment.assignment_kind,
            "usage_label": assignment.usage_label,
            "note": assignment.note,
            "material_name": material_name,
            "overlay_text": self._assignment_overlay_text(assignment),
            "selection_value": (
                f"comp:{assignment.product_composition_id}"
                if assignment.assignment_kind == "composition_item" and assignment.product_composition_id
                else f"material:{assignment.fabric_id}"
                if assignment.assignment_kind == "material" and assignment.fabric_id
                else "custom"
                if assignment.assignment_kind == "custom"
                else ""
            ),
        }

    def _assignment_overlay_text(self, assignment: ProductGarmentZoneAssignment | None) -> str | None:
        if not assignment:
            return None

        if assignment.product_composition and assignment.product_composition.fabric:
            fabric = assignment.product_composition.fabric
            code = str(getattr(fabric, "public_id", "") or "").strip()
            if code:
                return code
            return str(getattr(fabric, "name", "") or "").strip() or assignment.usage_label

        if assignment.fabric:
            code = str(getattr(assignment.fabric, "public_id", "") or "").strip()
            if code:
                return code
            return str(getattr(assignment.fabric, "name", "") or "").strip() or assignment.usage_label

        return str(assignment.usage_label or "").strip() or None

    def _analyze_image(self, *, image_path: Path, source_image: str, category_key: str) -> dict[str, Any]:
        yolo_analysis = self._analyze_image_with_yolo(
            image_path=image_path,
            source_image=source_image,
            category_key=category_key,
        )
        if yolo_analysis is not None:
            return yolo_analysis

        with Image.open(image_path) as source:
            original = ImageOps.exif_transpose(source.convert("RGB"))
            working = original.copy()
            working.thumbnail((720, 720))

            mask = self._build_foreground_mask(working)
            bbox_small = mask.getbbox()
            if not bbox_small:
                bbox_small = (int(working.width * 0.18), int(working.height * 0.05), int(working.width * 0.82), int(working.height * 0.96))

            scale_x = original.width / working.width
            scale_y = original.height / working.height
            bbox = {
                "left": int(bbox_small[0] * scale_x),
                "top": int(bbox_small[1] * scale_y),
                "right": int(bbox_small[2] * scale_x),
                "bottom": int(bbox_small[3] * scale_y),
            }

            detections = self._build_detections(category_key, bbox, original.width, original.height)
            quality_score = round(min(0.95, max(0.45, ((bbox["right"] - bbox["left"]) * (bbox["bottom"] - bbox["top"])) / float(max(1, original.width * original.height)) + 0.4)), 2)

        return {
            "schema_version": self.SCHEMA_VERSION,
            "detector": self.DETECTOR_VERSION,
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "category": category_key,
            "source_image": source_image,
            "image_size": {"width": original.width, "height": original.height},
            "foreground_bbox": bbox,
            "quality_score": quality_score,
            "detections": detections,
        }

    def _analyze_image_with_yolo(
        self,
        *,
        image_path: Path,
        source_image: str,
        category_key: str | None,
    ) -> dict[str, Any] | None:
        model, weights_path = self._load_yolo_model()
        if model is None:
            return None

        device = str(current_app.config.get("GARMENT_AI_DEVICE") or "cpu")
        confidence = float(current_app.config.get("GARMENT_AI_CONFIDENCE") or 0.25)

        results = model.predict(
            source=str(image_path),
            conf=confidence,
            device=device,
            verbose=False,
        )

        detections = self._build_yolo_detections(results)
        if not detections:
            return None

        with Image.open(image_path) as source:
            original = ImageOps.exif_transpose(source.convert("RGB"))
            image_width, image_height = original.size

        foreground_bbox = self._bbox_from_detections(detections, image_width=image_width, image_height=image_height)
        quality_score = round(
            min(
                0.99,
                max(
                    0.5,
                    sum(float(item.get("confidence") or 0.0) for item in detections) / max(1, len(detections)),
                ),
            ),
            2,
        )

        return {
            "schema_version": self.SCHEMA_VERSION,
            "detector": f"yolo:{weights_path.name}",
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "category": category_key or "generic",
            "source_image": source_image,
            "image_size": {"width": image_width, "height": image_height},
            "foreground_bbox": foreground_bbox,
            "quality_score": quality_score,
            "detections": detections,
        }

    def _build_yolo_detections(self, results: list[Any]) -> list[dict[str, Any]]:
        detections: list[dict[str, Any]] = []
        class_counts: dict[str, int] = {}

        for result in results:
            names = getattr(result, "names", {}) or {}
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue

            xyxy = boxes.xyxy.cpu().tolist()
            confs = boxes.conf.cpu().tolist()
            classes = boxes.cls.cpu().tolist()

            for box, score, cls_id in zip(xyxy, confs, classes):
                class_name = str(names.get(int(cls_id), cls_id)).strip().lower()
                base_key = YOLO_CLASS_ZONE_KEYS.get(class_name, class_name.replace("-", "_").replace(" ", "_"))
                class_counts[base_key] = class_counts.get(base_key, 0) + 1
                key = base_key if class_counts[base_key] == 1 else f"{base_key}_{class_counts[base_key]}"
                left, top, right, bottom = [float(value) for value in box]
                width = max(1.0, right - left)
                height = max(1.0, bottom - top)

                detections.append(
                    {
                        "key": key,
                        "label": self._yolo_label_for_detection(base_key, class_counts[base_key]),
                        "kind": "area",
                        "confidence": round(float(score), 2),
                        "source": "yolo",
                        "class_name": class_name,
                        "box": {
                            "x": int(round(left)),
                            "y": int(round(top)),
                            "width": int(round(width)),
                            "height": int(round(height)),
                        },
                    }
                )

        detections.sort(
            key=lambda item: (
                int((item.get("box") or {}).get("y") or 0),
                int((item.get("box") or {}).get("x") or 0),
            )
        )
        return detections

    def _yolo_label_for_detection(self, base_key: str, index: int) -> str:
        label = YOLO_CLASS_LABELS.get(base_key, base_key.replace("_", " ").title())
        return label if index == 1 else f"{label} #{index}"

    def _bbox_from_detections(
        self,
        detections: list[dict[str, Any]],
        *,
        image_width: int,
        image_height: int,
    ) -> dict[str, int]:
        left = min(int((item.get("box") or {}).get("x") or 0) for item in detections)
        top = min(int((item.get("box") or {}).get("y") or 0) for item in detections)
        right = max(
            int((item.get("box") or {}).get("x") or 0) + int((item.get("box") or {}).get("width") or 0)
            for item in detections
        )
        bottom = max(
            int((item.get("box") or {}).get("y") or 0) + int((item.get("box") or {}).get("height") or 0)
            for item in detections
        )
        return {
            "left": self._clamp(left, 0, max(0, image_width - 1)),
            "top": self._clamp(top, 0, max(0, image_height - 1)),
            "right": self._clamp(right, 1, image_width),
            "bottom": self._clamp(bottom, 1, image_height),
        }

    def _build_foreground_mask(self, image: Image.Image) -> Image.Image:
        corner_size = max(8, min(image.width, image.height) // 8)
        corners = [
            image.crop((0, 0, corner_size, corner_size)),
            image.crop((image.width - corner_size, 0, image.width, corner_size)),
            image.crop((0, image.height - corner_size, corner_size, image.height)),
            image.crop((image.width - corner_size, image.height - corner_size, image.width, image.height)),
        ]

        totals = [0.0, 0.0, 0.0]
        pixel_count = 0
        for patch in corners:
            stat = ImageStat.Stat(patch)
            for index in range(3):
                totals[index] += stat.mean[index] * patch.width * patch.height
            pixel_count += patch.width * patch.height

        bg_color = tuple(int(value / max(pixel_count, 1)) for value in totals)
        background = Image.new("RGB", image.size, bg_color)
        difference = ImageChops.difference(image, background)
        grayscale = ImageOps.grayscale(difference)
        stat = ImageStat.Stat(grayscale)
        threshold = max(24, int(stat.mean[0] + stat.stddev[0] * 0.85))

        mask = grayscale.point(lambda value: 255 if value >= threshold else 0)
        mask = mask.filter(ImageFilter.MedianFilter(size=5))
        mask = mask.filter(ImageFilter.MaxFilter(size=5))
        return mask

    def _build_detections(
        self,
        category_key: str,
        bbox: dict[str, int],
        image_width: int,
        image_height: int,
    ) -> list[dict[str, Any]]:
        template = GARMENT_TEMPLATES.get(category_key, [])
        box_width = max(1, bbox["right"] - bbox["left"])
        box_height = max(1, bbox["bottom"] - bbox["top"])
        detections: list[dict[str, Any]] = []

        for index, item in enumerate(template):
            width = max(18, int(box_width * float(item["w"])))
            height = max(18, int(box_height * float(item["h"])))
            center_x = bbox["left"] + int(box_width * float(item["x"]))
            center_y = bbox["top"] + int(box_height * float(item["y"]))
            left = self._clamp(center_x - width // 2, 0, max(0, image_width - width))
            top = self._clamp(center_y - height // 2, 0, max(0, image_height - height))
            confidence = round(max(0.56, 0.84 - index * 0.03), 2)

            detections.append(
                {
                    "key": item["key"],
                    "label": item["label"],
                    "kind": "area",
                    "confidence": confidence,
                    "source": "template+silhouette",
                    "box": {
                        "x": int(left),
                        "y": int(top),
                        "width": int(width),
                        "height": int(height),
                    },
                }
            )

        return detections

    def _save_annotation_image(self, product, image_path: Path, analysis: dict[str, Any]) -> str:
        annotations_dir = self._resolve_upload_folder() / "annotations"
        annotations_dir.mkdir(parents=True, exist_ok=True)

        filename = f"product_{getattr(product, 'id', 'unknown')}_garment_map.png"
        output_path = annotations_dir / filename

        colors = [
            (13, 110, 253, 220),
            (25, 135, 84, 220),
            (220, 53, 69, 220),
            (255, 193, 7, 220),
            (111, 66, 193, 220),
            (13, 202, 240, 220),
            (253, 126, 20, 220),
        ]

        with Image.open(image_path) as source:
            image = ImageOps.exif_transpose(source.convert("RGBA"))
            overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            assignments = self._load_assignments_by_zone(getattr(product, "id", None))
            label_font = self._load_font(max(18, image.width // 34), bold=True)
            small_font = self._load_font(max(14, image.width // 48), bold=False)
            components = self._build_visual_components(
                detections=analysis.get("detections") or [],
                assignments=assignments,
            )

            for index, component in enumerate(components):
                color = colors[index % len(colors)]
                self._draw_component_overlay(
                    draw=draw,
                    component=component,
                    color=color,
                    image_size=image.size,
                    label_font=label_font,
                    small_font=small_font,
                )

            result = Image.alpha_composite(image, overlay).convert("RGB")
            result.save(output_path, format="PNG", optimize=True)

        return f"/uploads/annotations/{filename}"

    def _build_visual_components(
        self,
        *,
        detections: list[dict[str, Any]],
        assignments: dict[str, ProductGarmentZoneAssignment],
    ) -> list[dict[str, Any]]:
        zones: list[dict[str, Any]] = []
        for detection in detections:
            key = str(detection.get("key") or "").strip()
            assignment = assignments.get(key)
            zone = dict(detection)
            zone["assignment"] = self._serialize_assignment(assignment)
            zone["profile"] = self._zone_profile(key, detection.get("label"))
            zones.append(zone)
        return self._build_component_view_model(zones)

    def _draw_component_overlay(
        self,
        *,
        draw: ImageDraw.ImageDraw,
        component: dict[str, Any],
        color: tuple[int, int, int, int],
        image_size: tuple[int, int],
        label_font,
        small_font,
    ) -> None:
        zones = list(component.get("zone_keys") or [])
        related = [zone for zone in self._extract_component_zones(component) if zone.get("box")]
        if not related:
            return

        component_key = str(component.get("key") or "")
        label_text = self._component_overlay_label(component)
        accent = (color[0], color[1], color[2], 255)
        fill = (color[0], color[1], color[2], 56)
        stroke = max(3, image_size[0] // 420)

        for zone in related:
            box = zone.get("box") or {}
            x = int(box.get("x", 0))
            y = int(box.get("y", 0))
            w = int(box.get("width", 0))
            h = int(box.get("height", 0))

            if component_key in {"sleeves", "cuffs"}:
                points = [
                    (x + int(w * 0.14), y + int(h * 0.1)),
                    (x + int(w * 0.86), y + int(h * 0.06)),
                    (x + int(w * 0.94), y + int(h * 0.78)),
                    (x + int(w * 0.62), y + int(h * 0.94)),
                    (x + int(w * 0.18), y + int(h * 0.82)),
                ]
                draw.polygon(points, fill=fill, outline=accent, width=stroke)
            elif component_key == "neck_label":
                tag = [
                    (x + int(w * 0.18), y + int(h * 0.12)),
                    (x + int(w * 0.82), y + int(h * 0.12)),
                    (x + int(w * 0.82), y + int(h * 0.84)),
                    (x + int(w * 0.52), y + int(h * 0.98)),
                    (x + int(w * 0.18), y + int(h * 0.84)),
                ]
                draw.polygon(tag, fill=fill, outline=accent, width=stroke)
                hole_r = max(2, w // 18)
                cx = x + int(w * 0.5)
                cy = y + int(h * 0.28)
                draw.ellipse((cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r), fill=(255, 255, 255, 190))
            elif component_key == "closure":
                draw.rounded_rectangle(
                    (x + int(w * 0.34), y, x + int(w * 0.66), y + h),
                    radius=max(10, min(w, h) // 5),
                    fill=fill,
                    outline=accent,
                    width=stroke,
                )
            elif component_key == "hem_finish":
                draw.rounded_rectangle(
                    (x, y + int(h * 0.18), x + w, y + int(h * 0.82)),
                    radius=max(10, h // 2),
                    fill=fill,
                    outline=accent,
                    width=stroke,
                )
            elif component_key == "decoration":
                draw.ellipse((x, y, x + w, y + h), fill=fill, outline=accent, width=stroke)
            elif component_key == "pocket":
                draw.rounded_rectangle(
                    (x, y + int(h * 0.06), x + w, y + h),
                    radius=max(12, min(w, h) // 4),
                    fill=fill,
                    outline=accent,
                    width=stroke,
                )
                draw.line(
                    [(x + int(w * 0.12), y + int(h * 0.18)), (x + int(w * 0.88), y + int(h * 0.18))],
                    fill=accent,
                    width=max(2, stroke - 1),
                )
            elif component_key == "hood":
                points = [
                    (x + int(w * 0.16), y + h),
                    (x + int(w * 0.24), y + int(h * 0.28)),
                    (x + int(w * 0.44), y + int(h * 0.04)),
                    (x + int(w * 0.56), y + int(h * 0.04)),
                    (x + int(w * 0.76), y + int(h * 0.28)),
                    (x + int(w * 0.84), y + h),
                ]
                draw.polygon(points, fill=fill, outline=accent, width=stroke)
            else:
                draw.rounded_rectangle(
                    (x, y, x + w, y + h),
                    radius=max(12, min(w, h) // 4),
                    fill=fill,
                    outline=accent,
                    width=stroke,
                )

        union = self._component_union_box(related)
        self._draw_component_label_chip(
            draw=draw,
            union_box=union,
            label_text=label_text,
            sublabel=str(component.get("label") or ""),
            color=accent,
            image_size=image_size,
            label_font=label_font,
            small_font=small_font,
        )

    def _extract_component_zones(self, component: dict[str, Any]) -> list[dict[str, Any]]:
        return component.get("zones") or []

    def _component_union_box(self, zones: list[dict[str, Any]]) -> dict[str, int]:
        if not zones:
            return {"x": 0, "y": 0, "width": 1, "height": 1}
        xs: list[int] = []
        ys: list[int] = []
        x2s: list[int] = []
        y2s: list[int] = []
        for zone in zones:
            box = zone.get("box") or {}
            x = int(box.get("x", 0))
            y = int(box.get("y", 0))
            w = int(box.get("width", 0))
            h = int(box.get("height", 0))
            xs.append(x)
            ys.append(y)
            x2s.append(x + w)
            y2s.append(y + h)
        return {
            "x": min(xs),
            "y": min(ys),
            "width": max(x2s) - min(xs),
            "height": max(y2s) - min(ys),
        }

    def _component_overlay_label(self, component: dict[str, Any]) -> str:
        assignment = component.get("assignment") or {}
        overlay = str(assignment.get("overlay_text") or "").strip()
        if overlay:
            return overlay
        label = str(component.get("label") or "Component").strip()
        if len(label) <= 18:
            return label
        return label[:18].rstrip() + "..."

    def _draw_component_label_chip(
        self,
        *,
        draw: ImageDraw.ImageDraw,
        union_box: dict[str, int],
        label_text: str,
        sublabel: str,
        color: tuple[int, int, int, int],
        image_size: tuple[int, int],
        label_font,
        small_font,
    ) -> None:
        x = int(union_box["x"])
        y = int(union_box["y"])
        width = int(union_box["width"])
        height = int(union_box["height"])
        chip_x = max(12, min(x + width + 14, image_size[0] - 240))
        chip_y = max(12, y + max(0, height // 3) - 16)

        label_box = draw.textbbox((0, 0), label_text, font=label_font)
        sublabel_box = draw.textbbox((0, 0), sublabel, font=small_font)
        chip_w = max(label_box[2] - label_box[0], sublabel_box[2] - sublabel_box[0]) + 26
        chip_h = (label_box[3] - label_box[1]) + (sublabel_box[3] - sublabel_box[1]) + 22
        chip_x = max(10, min(chip_x, image_size[0] - chip_w - 10))
        chip_y = max(10, min(chip_y, image_size[1] - chip_h - 10))

        center_x = x + width
        center_y = y + height // 2
        draw.line(
            [(center_x, center_y), (chip_x, chip_y + chip_h // 2)],
            fill=(color[0], color[1], color[2], 210),
            width=max(2, image_size[0] // 520),
        )
        dot_r = max(3, image_size[0] // 320)
        draw.ellipse(
            (center_x - dot_r, center_y - dot_r, center_x + dot_r, center_y + dot_r),
            fill=(color[0], color[1], color[2], 255),
        )

        draw.rounded_rectangle(
            (chip_x, chip_y, chip_x + chip_w, chip_y + chip_h),
            radius=14,
            fill=(12, 23, 42, 220),
            outline=(color[0], color[1], color[2], 255),
            width=max(2, image_size[0] // 480),
        )
        draw.text((chip_x + 12, chip_y + 8), label_text, fill=(255, 255, 255, 255), font=label_font)
        draw.text((chip_x + 12, chip_y + 12 + (label_box[3] - label_box[1])), sublabel, fill=(196, 210, 228, 255), font=small_font)

    def _load_font(self, size: int, *, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        font_name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        font_path = Path(current_app.static_folder) / "fonts" / font_name
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except Exception:
            return ImageFont.load_default()

    def _annotation_label_for_detection(
        self,
        detection: dict[str, Any],
        assignment: ProductGarmentZoneAssignment | None,
    ) -> str:
        base = str(detection.get("label") or detection.get("key") or "Detail")
        overlay = self._assignment_overlay_text(assignment)
        if overlay:
            return overlay
        return base

    def _display_box_for_detection(
        self,
        box: dict[str, Any],
        *,
        zone_key: str,
        assignment: ProductGarmentZoneAssignment | None,
    ) -> dict[str, int]:
        x = int(box.get("x", 0))
        y = int(box.get("y", 0))
        width = max(1, int(box.get("width", 0)))
        height = max(1, int(box.get("height", 0)))

        material_type = self._assignment_material_type(assignment)
        role = str(getattr(assignment, "usage_label", "") or "").strip().lower()

        if zone_key == "neck_label_area" or material_type == "label":
            return self._compact_box(x, y, width, height, scale_w=0.62, scale_h=0.58, offset_y=0.08)

        if material_type == "button":
            return self._compact_box(x, y, width, height, scale_w=0.38, scale_h=0.34, offset_y=0.0)

        if material_type == "zipper":
            return self._compact_box(x, y, width, height, scale_w=0.34, scale_h=0.88, offset_y=0.0)

        if "print" in role or "embroidery" in role or "patch" in role:
            return self._compact_box(x, y, width, height, scale_w=0.72, scale_h=0.72, offset_y=0.0)

        return {"x": x, "y": y, "width": width, "height": height}

    def _compact_box(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        scale_w: float,
        scale_h: float,
        offset_y: float,
    ) -> dict[str, int]:
        new_width = max(16, int(width * scale_w))
        new_height = max(14, int(height * scale_h))
        center_x = x + width // 2
        center_y = y + height // 2 + int(height * offset_y)
        new_x = center_x - new_width // 2
        new_y = center_y - new_height // 2
        return {"x": new_x, "y": new_y, "width": new_width, "height": new_height}

    def _assignment_material_type(self, assignment: ProductGarmentZoneAssignment | None) -> str:
        if not assignment:
            return ""
        if assignment.product_composition and assignment.product_composition.fabric:
            return str(getattr(assignment.product_composition.fabric, "material_type", "") or "").strip().lower()
        if assignment.fabric:
            return str(getattr(assignment.fabric, "material_type", "") or "").strip().lower()
        return ""

    def _load_assignments_by_zone(self, product_id: int | None) -> dict[str, ProductGarmentZoneAssignment]:
        if not product_id:
            return {}
        rows = (
            ProductGarmentZoneAssignment.query
            .filter(ProductGarmentZoneAssignment.product_id == product_id)
            .all()
        )
        return {str(row.zone_key): row for row in rows}

    def _remove_annotation_file(self, value: str) -> None:
        try:
            path = self._resolve_image_path(value)
        except Exception:
            return
        upload_folder = self._resolve_upload_folder()
        try:
            path.relative_to(upload_folder)
        except ValueError:
            return
        if path.exists() and path.is_file():
            os.remove(path)

    def _clamp(self, value: int, minimum: int, maximum: int) -> int:
        return max(minimum, min(value, maximum))
