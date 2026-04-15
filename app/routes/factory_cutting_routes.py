from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import date, timedelta
from math import ceil
import json
from ..services.cutting_order_service import CuttingOrderService
from ..forms import CuttingOrderForm, CuttingOrderMaterialForm
from ..models import Product, Fabric
from ..activity_log import ActivityLog
from ..services.activity_log_service import activity_log

cutting_bp = Blueprint("cutting", __name__, url_prefix="/factory/cutting")
cutting_service = CuttingOrderService()

COMPONENT_NOTE_MARKER = "CUT_COMPONENTS_JSON::"


def _extract_component_rows(note_text: str | None):
    raw = str(note_text or "").strip()
    if not raw or COMPONENT_NOTE_MARKER not in raw:
        return [], raw
    marker_index = raw.rfind(COMPONENT_NOTE_MARKER)
    clean_note = raw[:marker_index].strip()
    payload = raw[marker_index + len(COMPONENT_NOTE_MARKER):].strip()
    try:
        rows = json.loads(payload)
        if isinstance(rows, list):
            normalized = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                component_name = str(row.get("component_name") or "").strip()
                pieces = int(row.get("pieces") or 0)
                fabric_id = int(row.get("fabric_id") or 0)
                used_meters = float(row.get("used_meters") or 0)
                if not component_name or pieces <= 0 or fabric_id <= 0 or used_meters <= 0:
                    continue
                normalized.append({
                    "component_name": component_name,
                    "pieces": pieces,
                    "fabric_id": fabric_id,
                    "used_meters": used_meters,
                })
            return normalized, clean_note
    except Exception:
        pass
    return [], clean_note


def _merge_note_with_component_rows(note_text: str | None, component_rows: list[dict]):
    clean_note = str(note_text or "").strip()
    payload = json.dumps(component_rows, ensure_ascii=True)
    if clean_note:
        return f"{clean_note}\n{COMPONENT_NOTE_MARKER}{payload}"
    return f"{COMPONENT_NOTE_MARKER}{payload}"


def _sewing_output_rows(factory_id: int | None):
    if not factory_id:
        return []
    try:
        rows = (
            ActivityLog.query
            .filter(
                ActivityLog.entity == "cutting_sewing_output",
                ActivityLog.action == "log",
            )
            .order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc())
            .limit(2000)
            .all()
        )
    except Exception:
        return []

    result = []
    for row in rows:
        payload = row.after if isinstance(row.after, dict) else {}
        if int(payload.get("factory_id") or 0) != int(factory_id or 0):
            continue
        sewn_pieces = int(payload.get("sewn_pieces") or 0)
        product_id = int(payload.get("product_id") or 0)
        component_name = str(payload.get("component_name") or "").strip()
        if sewn_pieces <= 0 or product_id <= 0 or not component_name:
            continue
        result.append({
            "timestamp": row.timestamp,
            "product_id": product_id,
            "product_name": str(payload.get("product_name") or f"Product #{product_id}"),
            "component_name": component_name,
            "sewn_pieces": sewn_pieces,
        })
    return result


def _component_suggestions_by_product(factory_id: int | None):
    suggestions = {}
    if not factory_id:
        return suggestions

    orders = cutting_service.list_cutting_orders(factory_id)
    for order in orders:
        component_rows, _ = _extract_component_rows(getattr(order, "notes", None))
        if not component_rows:
            continue
        product_id = int(getattr(order, "product_id", 0) or 0)
        if product_id <= 0:
            continue
        if product_id not in suggestions:
            suggestions[product_id] = set()
        for row in component_rows:
            name = str(row.get("component_name") or "").strip()
            if name:
                suggestions[product_id].add(name)

    for row in _sewing_output_rows(factory_id):
        product_id = int(row.get("product_id") or 0)
        if product_id <= 0:
            continue
        if product_id not in suggestions:
            suggestions[product_id] = set()
        name = str(row.get("component_name") or "").strip()
        if name:
            suggestions[product_id].add(name)

    return {
        str(product_id): sorted(names, key=lambda v: v.lower())
        for product_id, names in suggestions.items()
        if names
    }

@cutting_bp.route("/orders")
@login_required
def cutting_order_list():
    orders = cutting_service.list_cutting_orders(current_user.factory_id)
    factory_products = Product.query.filter_by(factory_id=current_user.factory_id).order_by(Product.name.asc()).all()
    target_pieces = request.args.get("target_pieces", type=int)
    benchmark_ppm = request.args.get("benchmark_ppm", type=float)
    if target_pieces is not None and target_pieces <= 0:
        target_pieces = None
    if benchmark_ppm is not None and benchmark_ppm <= 0:
        benchmark_ppm = None

    today = date.today()
    last_7_start = today - timedelta(days=6)
    last_30_start = today - timedelta(days=29)

    status_counts = {"open": 0, "in_progress": 0, "closed": 0, "other": 0}
    total_sets = 0
    total_material_lines = 0
    total_material_cost = 0.0
    total_used_meters = 0.0
    sets_last_7 = 0
    sets_last_30 = 0
    orders_last_7 = 0
    orders_last_30 = 0

    product_rollup = {}
    material_rollup = {}
    enriched_orders = []
    component_cut_totals = {}

    for order in orders:
        status = (order.status or "").strip().lower()
        if status in status_counts:
            status_counts[status] += 1
        else:
            status_counts["other"] += 1

        sets_cut = int(order.sets_cut or 0)
        total_sets += sets_cut

        order_date = order.cut_date
        if order_date and order_date >= last_7_start:
            orders_last_7 += 1
            sets_last_7 += sets_cut
        if order_date and order_date >= last_30_start:
            orders_last_30 += 1
            sets_last_30 += sets_cut

        product_name = order.product.name if getattr(order, "product", None) else f"Product #{order.product_id}"
        product_key = int(order.product_id or 0)
        if product_key not in product_rollup:
            product_rollup[product_key] = {
                "product_id": product_key,
                "name": product_name,
                "sets": 0,
                "orders": 0,
                "used_meters": 0.0,
                "cost": 0.0,
            }
        product_rollup[product_key]["sets"] += sets_cut
        product_rollup[product_key]["orders"] += 1

        row_used_meters = 0.0
        row_cost = 0.0

        for material in (order.materials or []):
            total_material_lines += 1
            material_cost = float(getattr(material, "total_cost_snapshot", 0) or 0)
            used_amount = float(getattr(material, "used_amount", 0) or 0)
            total_material_cost += material_cost
            total_used_meters += used_amount
            row_used_meters += used_amount
            row_cost += material_cost
            product_rollup[product_key]["used_meters"] += used_amount
            product_rollup[product_key]["cost"] += material_cost

            material_name = (
                material.material.name if getattr(material, "material", None)
                else f"Material #{material.material_id}"
            )
            if material_name not in material_rollup:
                material_rollup[material_name] = {
                    "name": material_name,
                    "used": 0.0,
                    "cost": 0.0,
                    "entries": 0,
                }
            material_rollup[material_name]["used"] += used_amount
            material_rollup[material_name]["cost"] += material_cost
            material_rollup[material_name]["entries"] += 1

        pieces_per_meter = (sets_cut / row_used_meters) if row_used_meters > 0 else 0.0
        cost_per_piece = (row_cost / sets_cut) if sets_cut > 0 else 0.0
        ppm_gap = (pieces_per_meter - benchmark_ppm) if benchmark_ppm is not None else None
        yield_state = None
        if ppm_gap is not None:
            if ppm_gap >= 0.2:
                yield_state = "good"
            elif ppm_gap <= -0.2:
                yield_state = "low"
            else:
                yield_state = "ok"
        enriched_orders.append({
            "order": order,
            "used_meters": row_used_meters,
            "row_cost": row_cost,
            "pieces_per_meter": pieces_per_meter,
            "cost_per_piece": cost_per_piece,
            "ppm_gap": ppm_gap,
            "yield_state": yield_state,
            "component_rows": [],
            "clean_note": (order.notes or "").strip(),
        })

        component_rows, clean_note = _extract_component_rows(order.notes)
        if component_rows:
            enriched_orders[-1]["component_rows"] = component_rows
            enriched_orders[-1]["clean_note"] = clean_note
            for row in component_rows:
                key = (int(order.product_id or 0), str(row["component_name"]).strip().lower())
                if key not in component_cut_totals:
                    component_cut_totals[key] = {
                        "product_id": int(order.product_id or 0),
                        "product_name": order.product.name if getattr(order, "product", None) else f"Product #{order.product_id}",
                        "component_name": str(row["component_name"]).strip(),
                        "cut_pieces": 0,
                        "sewn_pieces": 0,
                    }
                component_cut_totals[key]["cut_pieces"] += int(row["pieces"] or 0)

    sewing_outputs = _sewing_output_rows(current_user.factory_id)
    for row in sewing_outputs:
        key = (int(row["product_id"] or 0), str(row["component_name"]).strip().lower())
        if key not in component_cut_totals:
            component_cut_totals[key] = {
                "product_id": int(row["product_id"] or 0),
                "product_name": row["product_name"],
                "component_name": str(row["component_name"]).strip(),
                "cut_pieces": 0,
                "sewn_pieces": 0,
            }
        component_cut_totals[key]["sewn_pieces"] += int(row["sewn_pieces"] or 0)

    sewer_balance_rows = []
    sewer_anomalies = []
    for row in component_cut_totals.values():
        in_hand = int(row["cut_pieces"] or 0) - int(row["sewn_pieces"] or 0)
        payload = {
            **row,
            "in_hand": in_hand,
        }
        if in_hand < 0:
            sewer_anomalies.append(payload)
        sewer_balance_rows.append(payload)
    sewer_balance_rows.sort(key=lambda item: (item["product_name"], item["component_name"]))
    sewer_anomalies.sort(key=lambda item: (item["product_name"], item["component_name"]))

    backlog_sets = 0
    for order in orders:
        status = (order.status or "").strip().lower()
        if status in ("open", "in_progress"):
            backlog_sets += int(order.sets_cut or 0)

    daily_pace = (sets_last_7 / 7.0) if sets_last_7 > 0 else 0.0
    estimated_days_to_clear = ceil(backlog_sets / daily_pace) if backlog_sets > 0 and daily_pace > 0 else None

    avg_sets_per_order = round(total_sets / len(orders), 1) if orders else 0
    avg_material_lines_per_order = round(total_material_lines / len(orders), 1) if orders else 0
    avg_pieces_per_meter = (total_sets / total_used_meters) if total_used_meters > 0 else 0.0
    avg_cost_per_piece = (total_material_cost / total_sets) if total_sets > 0 else 0.0
    avg_ppm_gap = (avg_pieces_per_meter - benchmark_ppm) if benchmark_ppm is not None else None

    remaining_pieces = None
    target_progress_pct = None
    if target_pieces is not None:
        remaining_pieces = max(target_pieces - total_sets, 0)
        target_progress_pct = min((total_sets / target_pieces) * 100.0, 100.0) if target_pieces > 0 else 0.0

    top_products = sorted(
        product_rollup.values(),
        key=lambda row: (-int(row["sets"] or 0), -int(row["orders"] or 0), row["name"]),
    )[:5]
    top_materials = sorted(
        material_rollup.values(),
        key=lambda row: (-float(row["cost"] or 0), -float(row["used"] or 0), row["name"]),
    )[:5]

    product_progress_rows = []
    for row in sorted(product_rollup.values(), key=lambda item: (-int(item["sets"] or 0), item["name"]))[:8]:
        product_target = request.args.get(f"target_product_{row['product_id']}", type=int)
        if product_target is not None and product_target <= 0:
            product_target = None
        row_ppm = (float(row["sets"] or 0) / float(row["used_meters"] or 0)) if float(row["used_meters"] or 0) > 0 else 0.0
        row_cpp = (float(row["cost"] or 0) / float(row["sets"] or 0)) if float(row["sets"] or 0) > 0 else 0.0
        row_remaining = max(int(product_target or 0) - int(row["sets"] or 0), 0) if product_target else None
        row_progress_pct = min((float(row["sets"] or 0) / float(product_target)) * 100.0, 100.0) if product_target else None
        product_progress_rows.append({
            **row,
            "target": product_target,
            "remaining": row_remaining,
            "progress_pct": row_progress_pct,
            "pieces_per_meter": row_ppm,
            "cost_per_piece": row_cpp,
        })

    return render_template(
        "factory/cutting_order_list.html",
        orders=orders,
        enriched_orders=enriched_orders,
        status_counts=status_counts,
        total_sets=total_sets,
        total_used_meters=total_used_meters,
        backlog_sets=backlog_sets,
        sets_last_7=sets_last_7,
        sets_last_30=sets_last_30,
        orders_last_7=orders_last_7,
        orders_last_30=orders_last_30,
        total_material_cost=total_material_cost,
        avg_pieces_per_meter=avg_pieces_per_meter,
        avg_cost_per_piece=avg_cost_per_piece,
        avg_ppm_gap=avg_ppm_gap,
        benchmark_ppm=benchmark_ppm,
        avg_sets_per_order=avg_sets_per_order,
        avg_material_lines_per_order=avg_material_lines_per_order,
        target_pieces=target_pieces,
        remaining_pieces=remaining_pieces,
        target_progress_pct=target_progress_pct,
        estimated_days_to_clear=estimated_days_to_clear,
        top_products=top_products,
        top_materials=top_materials,
        product_progress_rows=product_progress_rows,
        sewer_balance_rows=sewer_balance_rows,
        sewer_anomalies=sewer_anomalies,
        factory_products=factory_products,
    )

@cutting_bp.route("/orders/<int:order_id>")
@login_required
def cutting_order_detail(order_id):
    order = cutting_service.get_cutting_order(order_id, current_user.factory_id)
    if not order:
        flash("Cutting order not found.", "danger")
        return redirect(url_for("cutting.cutting_order_list"))
    return render_template("factory/cutting_order_detail.html", order=order)


@cutting_bp.route("/sewing-output/log", methods=["POST"])
@login_required
def cutting_sewing_output_log():
    product_id = request.form.get("product_id", type=int)
    component_name = (request.form.get("component_name") or "").strip()
    sewn_pieces = request.form.get("sewn_pieces", type=int)

    if not product_id or not component_name or not sewn_pieces or sewn_pieces <= 0:
        flash("Provide product, component name, and sewn pieces (> 0).", "warning")
        return redirect(url_for("cutting.cutting_order_list"))

    product = Product.query.filter_by(id=product_id, factory_id=current_user.factory_id).first()
    if not product:
        flash("Selected product is not available in this factory.", "warning")
        return redirect(url_for("cutting.cutting_order_list"))

    activity_log.log(
        action="log",
        entity="cutting_sewing_output",
        entity_id=product_id,
        after={
            "factory_id": int(current_user.factory_id or 0),
            "product_id": int(product.id),
            "product_name": product.name,
            "component_name": component_name,
            "sewn_pieces": int(sewn_pieces),
        },
        comment="Sewing output logged from cutting operations dashboard.",
    )

    flash("Sewn output logged. Sewer balance updated.", "success")
    return redirect(url_for("cutting.cutting_order_list"))

@cutting_bp.route("/orders/create", methods=["GET", "POST"])
@login_required
def cutting_order_create():
    products = Product.query.filter_by(factory_id=current_user.factory_id).all()
    fabrics = Fabric.query.filter_by(factory_id=current_user.factory_id).all()
    fabric_ids = {int(row.id) for row in fabrics}
    component_suggestions_by_product = _component_suggestions_by_product(current_user.factory_id)
    form = CuttingOrderForm()
    form.product_id.choices = [(p.id, p.name) for p in products]

    def _build_material_rows():
        rows = []
        for index, material_form in enumerate(form.materials):
            fabric = fabrics[index] if index < len(fabrics) else None
            if fabric is None:
                continue
            rows.append({
                "form": material_form,
                "fabric": fabric,
            })
        return rows

    if request.method == "POST" and form.validate_on_submit():
        component_names = request.form.getlist("component_name[]")
        component_pieces_list = request.form.getlist("component_pieces[]")
        component_fabric_ids = request.form.getlist("component_fabric_id[]")
        component_used_meters_list = request.form.getlist("component_used_meters[]")

        component_rows = []
        max_rows = max(
            len(component_names),
            len(component_pieces_list),
            len(component_fabric_ids),
            len(component_used_meters_list),
            0,
        )
        for idx in range(max_rows):
            component_name = str(component_names[idx] if idx < len(component_names) else "").strip()
            try:
                pieces = int(component_pieces_list[idx] if idx < len(component_pieces_list) else 0)
            except (TypeError, ValueError):
                pieces = 0
            try:
                fabric_id = int(component_fabric_ids[idx] if idx < len(component_fabric_ids) else 0)
            except (TypeError, ValueError):
                fabric_id = 0
            try:
                used_meters = float(component_used_meters_list[idx] if idx < len(component_used_meters_list) else 0)
            except (TypeError, ValueError):
                used_meters = 0.0

            if not component_name and pieces <= 0 and fabric_id <= 0 and used_meters <= 0:
                continue
            if not component_name or pieces <= 0 or fabric_id <= 0 or used_meters <= 0:
                flash("Each component row needs component name, pieces, fabric, and used meters.", "warning")
                return render_template(
                    "factory/cutting_order_create.html",
                    form=form,
                    material_rows=_build_material_rows(),
                    fabrics=fabrics,
                    component_suggestions_by_product=component_suggestions_by_product,
                )
            if fabric_id not in fabric_ids:
                flash("One component row uses a fabric outside this factory.", "warning")
                return render_template(
                    "factory/cutting_order_create.html",
                    form=form,
                    material_rows=_build_material_rows(),
                    fabrics=fabrics,
                    component_suggestions_by_product=component_suggestions_by_product,
                )
            component_rows.append({
                "component_name": component_name,
                "pieces": pieces,
                "fabric_id": fabric_id,
                "used_meters": used_meters,
            })

        materials = []
        final_pieces_cut = int(form.sets_cut.data or 0)
        final_notes = form.notes.data

        if component_rows:
            material_usage_map = {}
            total_component_pieces = 0
            for row in component_rows:
                total_component_pieces += int(row["pieces"])
                material_usage_map[row["fabric_id"]] = material_usage_map.get(row["fabric_id"], 0.0) + float(row["used_meters"])
            materials = [
                {"material_id": int(fabric_id), "used_amount": float(used_amount)}
                for fabric_id, used_amount in material_usage_map.items()
                if float(used_amount) > 0
            ]
            if total_component_pieces != final_pieces_cut:
                flash(
                    f"Pieces Cut was adjusted from {final_pieces_cut} to {total_component_pieces} based on component rows.",
                    "info",
                )
            final_pieces_cut = int(total_component_pieces)
            final_notes = _merge_note_with_component_rows(form.notes.data, component_rows)
        else:
            for mform in form.materials.entries:
                used_amount = float(mform.used_amount.data or 0)
                if used_amount <= 0:
                    continue
                materials.append({
                    "material_id": int(mform.material_id.data),
                    "used_amount": used_amount,
                })

        if not materials:
            flash("Add at least one used fabric amount greater than 0.", "warning")
            return render_template(
                "factory/cutting_order_create.html",
                form=form,
                material_rows=_build_material_rows(),
                fabrics=fabrics,
                component_suggestions_by_product=component_suggestions_by_product,
            )

        order = cutting_service.create_cutting_order(
            factory_id=current_user.factory_id,
            product_id=form.product_id.data,
            cut_date=form.cut_date.data,
            sets_cut=final_pieces_cut,
            materials=materials,
            notes=final_notes,
            created_by_id=current_user.id,
        )
        flash("Cutting order created.", "success")
        return redirect(url_for("cutting.cutting_order_detail", order_id=order.id))

    # Prepopulate materials for GET
    if request.method == "GET" and not form.materials.entries:
        form.cut_date.data = date.today()
        for fabric in fabrics:
            mform = CuttingOrderMaterialForm()
            mform.material_id.data = fabric.id
            mform.used_amount.data = 0.0
            form.materials.append_entry(mform.data)

    material_rows = _build_material_rows()

    return render_template(
        "factory/cutting_order_create.html",
        form=form,
        material_rows=material_rows,
        fabrics=fabrics,
        component_suggestions_by_product=component_suggestions_by_product,
    )
