from flask import Blueprint, render_template, request, redirect, url_for, Response, send_file
from flask_login import login_required
from io import BytesIO
from datetime import datetime
from ..auth_utils import roles_required


import qrcode

from ..services.fabric_service import FabricService
from ..models import Fabric

fabrics_bp = Blueprint("fabrics", __name__, url_prefix="/fabrics")
service = FabricService()


@fabrics_bp.route("/", methods=["GET"])
@login_required
def list():
    query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "name")
    category = request.args.get("category", "").strip()

    fabrics = service.search_fabrics(query or None, sort, category or None)
    cuts = service.recent_cuts()
    any_low_stock = service.any_low_stock(fabrics)
    categories = service.get_categories()

    return render_template(
        "fabrics/list.html",
        fabrics=fabrics,
        cuts=cuts,
        q=query,
        sort=sort,
        any_low_stock=any_low_stock,
        categories=categories,
        selected_category=category,
    )


@fabrics_bp.route("/add", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def add():
    name = request.form.get("name", "").strip()
    color = request.form.get("color", "").strip() or None
    unit = request.form.get("unit", "").strip() or "kg"
    quantity = float(request.form.get("quantity", "0") or 0)
    price_raw = request.form.get("price_per_unit", "").strip()
    price_per_unit = float(price_raw) if price_raw else None
    price_currency = request.form.get("price_currency", "UZS").strip() or "UZS"
    category = request.form.get("category", "").strip() or None

    status, data = service.add_or_suggest_merge(
        name=name,
        color=color,
        unit=unit,
        quantity=quantity,
        price_per_unit=price_per_unit,
        price_currency=price_currency,
        category=category,
    )

    if status == "suggest_merge":
        existing, new_data = data
        return render_template(
            "fabrics/merge_confirm.html",
            existing=existing,
            new=new_data,
        )

    return redirect(url_for("fabrics.list"))


@fabrics_bp.route("/merge", methods=["POST"])
@roles_required("admin", "manager")
@login_required
def merge():
    existing_id = int(request.form["existing_id"])
    quantity = float(request.form["quantity"])
    price_raw = request.form.get("price_per_unit", "").strip()
    price_per_unit = float(price_raw) if price_raw else None
    price_currency = request.form.get("price_currency", "UZS")
    category = request.form.get("category", "").strip() or None

    service.confirm_merge(
        existing_id=existing_id,
        quantity=quantity,
        price_per_unit=price_per_unit,
        price_currency=price_currency,
        category=category,
    )

    return redirect(url_for("fabrics.list"))


@fabrics_bp.route("/create_new", methods=["POST"])
@roles_required("admin", "manager")
@login_required
def create_new():
    name = request.form.get("name", "").strip()
    color = request.form.get("color", "").strip() or None
    unit = request.form.get("unit", "").strip() or "kg"
    quantity = float(request.form.get("quantity", "0") or 0)
    price_raw = request.form.get("price_per_unit", "").strip()
    price_per_unit = float(price_raw) if price_raw else None
    price_currency = request.form.get("price_currency", "UZS").strip() or "UZS"
    category = request.form.get("category", "").strip() or None

    service.create_new(
        name=name,
        color=color,
        unit=unit,
        quantity=quantity,
        price_per_unit=price_per_unit,
        price_currency=price_currency,
        category=category,
    )

    return redirect(url_for("fabrics.list"))


@fabrics_bp.route("/<int:fabric_id>/cut", methods=["POST"])
@roles_required("admin", "manager")
@login_required
def cut(fabric_id):
    used_amount = float(request.form.get("used_amount", "0") or 0)
    service.cut_fabric(fabric_id, used_amount)
    return redirect(url_for("fabrics.list"))


@fabrics_bp.route("/export")

@login_required
@roles_required("admin", "manager")
def export():
    csv_bytes = service.export_csv()
    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=fabrics.csv"},
    )


@fabrics_bp.route("/<int:fabric_id>/qrcode")
@login_required
@roles_required("admin", "manager")
def qrcode_image(fabric_id):
    fabric = Fabric.query.get(fabric_id)
    if not fabric:
        return "Not found", 404

    text = (
        f"Fabric #{fabric.id}\n"
        f"Name: {fabric.name}\n"
        f"Color: {fabric.color}\n"
        f"Unit: {fabric.unit}\n"
        f"Qty: {fabric.quantity}\n"
        f"Currency: {fabric.price_currency}\n"
        f"Price: {fabric.price_per_unit}"
    )

    img = qrcode.make(text)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")
@fabrics_bp.route("/cuts", methods=["GET"])
@login_required
@roles_required("admin", "manager")
def cuts_history():
    date_from_str = request.args.get("from", "").strip()
    date_to_str = request.args.get("to", "").strip()

    date_from = None
    date_to = None
    date_format = "%Y-%m-%d"

    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, date_format).date()
        except ValueError:
            date_from = None

    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, date_format).date()
        except ValueError:
            date_to = None

    cuts = service.list_cuts(date_from, date_to)

    return render_template(
        "fabrics/cuts.html",
        cuts=cuts,
        date_from=date_from_str,
        date_to=date_to_str,
    )
