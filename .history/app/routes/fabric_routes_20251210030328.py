from app.telegram_notify import send_telegram_message
from app.telegram_config import LOW_STOCK_THRESHOLD
from app import db
from ..models import Fabric, Cut

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    Response,
    send_file,
)
from flask_login import login_required, current_user

from io import BytesIO
from datetime import datetime
import qrcode

from ..auth_utils import roles_required
from ..services.fabric_service import FabricService
from app.services.activity_log_service import ActivityLogService   # <-- ADDED
from ..models import Fabric

fabrics_bp = Blueprint("fabrics", __name__, url_prefix="/fabrics")
service = FabricService()
log_service = ActivityLogService()  # <-- ADDED


@fabrics_bp.route("/", methods=["GET"], endpoint="list")
@login_required
def list_fabrics():
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "name")
    selected_category = (request.args.get("category") or "").strip()
    category = selected_category or None
    page = request.args.get("page", 1, type=int)

    factory_id = current_user.factory_id

    has_filter = bool(q) or category is not None or sort != "name"
    view_all_flag = request.args.get("all", "0") == "1"
    is_latest_view = not view_all_flag and not has_filter

    if is_latest_view:
        fabrics = service.latest_fabrics(
            limit=5,
            factory_id=factory_id,
        )
        pagination = None
    else:
        per_page = 50
        fabrics, pagination = service.search_fabrics(
            query=q or None,
            sort=sort,
            category=category,
            page=page,
            per_page=per_page,
            factory_id=factory_id,
        )

    any_low_stock = service.any_low_stock(fabrics)
    cuts = service.recent_cuts(factory_id=factory_id)
    categories = service.get_categories(factory_id=factory_id)

    fabric_stats = service.get_dashboard_stats(factory_id=factory_id)
    usd_uzs_rate = fabric_stats.get("usd_uzs_rate")

    total_count = len(fabrics)
    total_qty = sum((f.quantity or 0) for f in fabrics)

    total_value_usd = 0.0
    total_value_uzs = 0.0
    for f in fabrics:
        if not f.price_per_unit:
            continue

        value = (f.quantity or 0) * float(f.price_per_unit)

        if f.price_currency == "USD":
            total_value_usd += value
        elif f.price_currency == "UZS":
            total_value_uzs += value

    view_stats = {
        "count": total_count,
        "qty": total_qty,
        "value_usd": total_value_usd,
        "value_uzs": total_value_uzs,
    }

    return render_template(
        "fabrics/list.html",
        fabrics=fabrics,
        pagination=pagination,
        any_low_stock=any_low_stock,
        q=q,
        sort=sort,
        categories=categories,
        selected_category=selected_category,
        cuts=cuts,
        LOW_STOCK_THRESHOLD=FabricService.LOW_STOCK_THRESHOLD,
        usd_uzs_rate=usd_uzs_rate,
        is_latest_view=is_latest_view,
        view_stats=view_stats,
    )


@fabrics_bp.route("/add", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def add():
    name = (request.form.get("name") or "").strip()
    color = (request.form.get("color") or "").strip() or None
    unit = (request.form.get("unit") or "").strip() or "kg"

    quantity_raw = request.form.get("quantity", "0") or 0
    try:
        quantity = float(quantity_raw)
    except ValueError:
        quantity = 0.0

    price_raw = (request.form.get("price_per_unit") or "").strip()
    price_per_unit = None
    if price_raw:
        try:
            price_per_unit = float(price_raw)
        except ValueError:
            price_per_unit = None

    price_currency = (request.form.get("price_currency") or "USD").strip() or "USD"
    category = (request.form.get("category") or "").strip() or None

    status, data = service.add_or_suggest_merge(
        factory_id=current_user.factory_id,
        name=name,
        color=color,
        unit=unit,
        quantity=quantity,
        price_per_unit=price_per_unit,
        price_currency=price_currency,
        category=category,
    )

    # 🔥 LOG ACTION
    log_service.log(
        user_id=current_user.id,
        factory_id=current_user.factory_id,
        action="fabric_add",
        details={
            "name": name,
            "color": color,
            "unit": unit,
            "quantity": quantity,
            "price_per_unit": price_per_unit,
            "currency": price_currency,
            "category": category,
            "status": status,
        },
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
@login_required
@roles_required("admin", "manager")
def merge():
    existing_id = int(request.form["existing_id"])

    quantity_raw = request.form.get("quantity", "0") or 0
    try:
        quantity = float(quantity_raw)
    except ValueError:
        quantity = 0.0

    price_raw = (request.form.get("price_per_unit") or "").strip()
    price_per_unit = None
    if price_raw:
        try:
            price_per_unit = float(price_raw)
        except ValueError:
            price_per_unit = None

    price_currency = (request.form.get("price_currency") or "USD").strip() or "USD"
    category = (request.form.get("category") or "").strip() or None

    service.confirm_merge(
        factory_id=current_user.factory_id,
        existing_id=existing_id,
        quantity=quantity,
        price_per_unit=price_per_unit,
        price_currency=price_currency,
        category=category,
    )

    # 🔥 LOG ACTION
    log_service.log(
        user_id=current_user.id,
        factory_id=current_user.factory_id,
        action="fabric_merge",
        details={
            "existing_id": existing_id,
            "added_quantity": quantity,
            "new_price": price_per_unit,
            "currency": price_currency,
            "category": category,
        },
    )

    return redirect(url_for("fabrics.list"))


@fabrics_bp.route("/create_new", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def create_new():
    name = (request.form.get("name") or "").strip()
    color = (request.form.get("color") or "").strip() or None
    unit = (request.form.get("unit") or "").strip() or "kg"

    quantity_raw = request.form.get("quantity", "0") or 0
    try:
        quantity = float(quantity_raw)
    except ValueError:
        quantity = 0.0

    price_raw = (request.form.get("price_per_unit") or "").strip()
    price_per_unit = None
    if price_raw:
        try:
            price_per_unit = float(price_raw)
        except ValueError:
            price_per_unit = None

    price_currency = (request.form.get("price_currency") or "USD").strip() or "USD"
    category = (request.form.get("category") or "").strip() or None

    fab = service.create_new(
        factory_id=current_user.factory_id,
        name=name,
        color=color,
        unit=unit,
        quantity=quantity,
        price_per_unit=price_per_unit,
        price_currency=price_currency,
        category=category,
    )

    # 🔥 LOG ACTION
    log_service.log(
        user_id=current_user.id,
        factory_id=current_user.factory_id,
        action="fabric_create_new",
        details={
            "fabric_id": fab.id,
            "name": name,
            "color": color,
            "unit": unit,
            "quantity": quantity,
            "price_per_unit": price_per_unit,
            "currency": price_currency,
            "category": category,
        },
    )

    return redirect(url_for("fabrics.list"))


@fabrics_bp.route("/<int:fabric_id>/cut", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def cut(fabric_id: int):
    used_raw = request.form.get("used_amount", "0") or 0
    try:
        used_amount = float(used_raw)
    except ValueError:
        used_amount = 0.0

    service.cut_fabric(
        factory_id=current_user.factory_id,
        fabric_id=fabric_id,
        used_amount=used_amount,
    )

    fab = Fabric.query.get(fabric_id)
    if fab:
        remaining = fab.quantity or 0.0

        try:
            if remaining <= LOW_STOCK_THRESHOLD:
                msg = (
                    "⚠️ <b>Мало ткани!</b>\n"
                    f"Название: <b>{fab.name}</b>\n"
                    f"Остаток: <b>{remaining:.2f} {fab.unit}</b>\n"
                    f"Цвет: {fab.color or '-'}"
                )
                send_telegram_message(msg)
        except Exception:
            pass

        # 🔥 LOG ACTION
        log_service.log(
            user_id=current_user.id,
            factory_id=current_user.factory_id,
            action="fabric_cut",
            details={
                "fabric_id": fabric_id,
                "used_amount": used_amount,
                "remaining": remaining,
            },
        )

    return redirect(url_for("fabrics.list"))


@fabrics_bp.route("/export", methods=["GET"])
@login_required
@roles_required("admin", "manager")
def export():
    csv_bytes = service.export_csv(factory_id=current_user.factory_id)
    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=fabrics.csv"},
    )


@fabrics_bp.route("/<int:fabric_id>/qrcode", methods=["GET"])
@login_required
@roles_required("admin", "manager")
def qrcode_image(fabric_id: int):
    fabric = (
        Fabric.query
        .filter_by(id=fabric_id, factory_id=current_user.factory_id)
        .first()
    )
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
    sort = request.args.get("sort", "date_desc")
    fabric_id = request.args.get("fabric_id", type=int)
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 50

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

    q_base = Cut.query.join(Fabric).filter(Fabric.factory_id == current_user.factory_id)

    if date_from:
        q_base = q_base.filter(Cut.cut_date >= date_from)
    if date_to:
        q_base = q_base.filter(Cut.cut_date <= date_to)

    selected_fabric_name = None
    if fabric_id:
        q_base = q_base.filter(Cut.fabric_id == fabric_id)
        fab_obj = (
            Fabric.query
            .filter_by(id=fabric_id, factory_id=current_user.factory_id)
            .first()
        )
        if fab_obj:
            selected_fabric_name = fab_obj.name

    if q:
        like = f"%{q.lower()}%"
        q_base = q_base.filter(db.func.lower(Fabric.name).like(like))

    q_stats = q_base
    all_cuts = q_stats.all()

    q_ordered = q_base
    if sort == "date_asc":
        q_ordered = q_ordered.order_by(Cut.cut_date.asc(), Cut.id.asc())
    elif sort == "amount_desc":
        q_ordered = q_ordered.order_by(Cut.used_amount.desc(), Cut.id.desc())
    elif sort == "amount_asc":
        q_ordered = q_ordered.order_by(Cut.used_amount.asc(), Cut.id.asc())
    else:
        sort = "date_desc"
        q_ordered = q_ordered.order_by(Cut.cut_date.desc(), Cut.id.desc())

    pagination = q_ordered.paginate(page=page, per_page=per_page, error_out=False)
    cuts = pagination.items

    totals_by_unit = {}
    for c in all_cuts:
        if c.used_amount is None:
            continue
        unit = c.fabric.unit if c.fabric and c.fabric.unit else ""
        if not unit:
            continue
        totals_by_unit.setdefault(unit, 0.0)
        totals_by_unit[unit] += float(c.used_amount)

    cuts_stats = {
        "total_cuts": len(all_cuts),
        "total_fabrics": len({c.fabric_id for c in all_cuts if c.fabric_id}),
        "totals_by_unit": totals_by_unit,
    }

    cuts_have_stock_info = any(
        hasattr(c, "remaining_quantity") and c.remaining_quantity is not None
        for c in all_cuts
    )
    cuts_have_comment = any(
        hasattr(c, "comment") and c.comment
        for c in all_cuts
    )

    fabric_options = (
        Fabric.query
        .filter(Fabric.factory_id == current_user.factory_id)
        .order_by(Fabric.name.asc())
        .all()
    )

    big_cut_threshold = 50

    return render_template(
        "fabrics/cuts.html",
        cuts=cuts,
        date_from=date_from_str,
        date_to=date_to_str,
        sort=sort,
        q=q,
        pagination=pagination,
        fabric_options=fabric_options,
        selected_fabric_id=fabric_id,
        selected_fabric_name=selected_fabric_name,
        cuts_stats=cuts_stats,
        cuts_have_stock_info=cuts_have_stock_info,
        cuts_have_comment=cuts_have_comment,
        big_cut_threshold=big_cut_threshold,
    )
