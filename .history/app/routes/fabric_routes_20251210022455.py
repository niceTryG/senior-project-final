from app.telegram_notify import send_telegram_message
from app.telegram_config import LOW_STOCK_THRESHOLD  # or hardcode for now (e.g., 3)

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
from ..models import Fabric


fabrics_bp = Blueprint("fabrics", __name__, url_prefix="/fabrics")
service = FabricService()


@fabrics_bp.route("/", methods=["GET"], endpoint="list")
@login_required
def list_fabrics():
    """
    Список тканей:
      - по умолчанию: последние 5 тканей (is_latest_view)
      - при фильтрах или all=1 → пагинированный список
    """
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "name")
    selected_category = (request.args.get("category") or "").strip()
    category = selected_category or None
    page = request.args.get("page", 1, type=int)

    factory_id = current_user.factory_id

    # меняли ли фильтры относительно дефолта?
    has_filter = bool(q) or category is not None or sort != "name"
    view_all_flag = request.args.get("all", "0") == "1"

    # дефолтный режим: показываем последние ткани (без фильтров и без all=1)
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

    # курс для мелкого текста (если используешь)
    fabric_stats = service.get_dashboard_stats(factory_id=factory_id)
    usd_uzs_rate = fabric_stats.get("usd_uzs_rate")

    # --- per-view smart stats ---
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
    """Добавление ткани (с умным merge-предложением)."""
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
    """Подтверждение слияния с уже существующей тканью."""
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

    return redirect(url_for("fabrics.list"))


@fabrics_bp.route("/create_new", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def create_new():
    """Создать новую ткань, даже если сервис предлагал merge."""
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

    service.create_new(
        factory_id=current_user.factory_id,
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
@login_required
@roles_required("admin", "manager")
def cut(fabric_id: int):
    """
    Списать часть ткани (раскрой) + при необходимости отправить
    Telegram-уведомление о низком остатке.
    """
    used_raw = request.form.get("used_amount", "0") or 0
    try:
        used_amount = float(used_raw)
    except ValueError:
        used_amount = 0.0

    # основной раскрой
    service.cut_fabric(
        factory_id=current_user.factory_id,
        fabric_id=fabric_id,
        used_amount=used_amount,
    )

    # обновлённая ткань
    fab = Fabric.query.get(fabric_id)
    if fab:
        remaining = fab.quantity or 0.0

        # Telegram-оповещение при низком остатке
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
            # Телега никогда не должна ломать UI
            pass

    return redirect(url_for("fabrics.list"))


@fabrics_bp.route("/export", methods=["GET"])
@login_required
@roles_required("admin", "manager")
def export():
    """Экспорт всех тканей фабрики в CSV."""
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
    """Сгенерировать QR-код с краткой инфой о ткани."""
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
    # --- read query params ---
    date_from_str = (request.args.get("from") or "").strip()
    date_to_str = (request.args.get("to") or "").strip()
    sort = (request.args.get("sort") or "date_desc").strip()
    q = (request.args.get("q") or "").strip()
    fabric_id_raw = (request.args.get("fabric_id") or "").strip()
    page = request.args.get("page", 1, type=int)

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

    fabric_id = None
    if fabric_id_raw:
        try:
            fabric_id = int(fabric_id_raw)
        except ValueError:
            fabric_id = None

    # --- query cuts via service (with pagination) ---
    cuts, pagination = service.list_cuts(
        date_from=date_from,
        date_to=date_to,
        factory_id=current_user.factory_id,
        fabric_id=fabric_id,
        q=q or None,
        sort=sort or "date_desc",
        page=page,
        per_page=50,
    )

    # --- fabric drop-down options ---
    fabric_options = (
        Fabric.query
        .filter(Fabric.factory_id == current_user.factory_id)
        .order_by(Fabric.name.asc())
        .all()
    )

    selected_fabric = None
    if fabric_id:
        selected_fabric = (
            Fabric.query
            .filter(Fabric.id == fabric_id, Fabric.factory_id == current_user.factory_id)
            .first()
        )
    selected_fabric_name = selected_fabric.name if selected_fabric else None

    # --- stats for summary cards ---
    totals_by_unit: dict[str, float] = {}
    fabric_ids_seen: set[int] = set()

    for c in cuts:
        if not c.fabric or c.used_amount is None:
            continue
        unit = c.fabric.unit or ""
        fabric_ids_seen.add(c.fabric.id)
        totals_by_unit.setdefault(unit, 0.0)
        totals_by_unit[unit] += c.used_amount

    # total cuts: if pagination exists, use pagination.total, else len(cuts)
    total_cuts = pagination.total if pagination else len(cuts)

    cuts_stats = {
        "total_cuts": total_cuts,
        "total_fabrics": len(fabric_ids_seen),
        "totals_by_unit": totals_by_unit,
    }

    # --- flags for template (optional columns) ---
    cuts_have_stock_info = any(
        hasattr(c, "remaining_quantity") and c.remaining_quantity is not None
        for c in cuts
    )
    cuts_have_comment = any(
        hasattr(c, "comment") and c.comment
        for c in cuts
    )

    big_cut_threshold = 50  # you can move this to service later if you want

    return render_template(
        "fabrics/cuts.html",
        cuts=cuts,
        pagination=pagination,
        date_from=date_from_str,
        date_to=date_to_str,
        sort=sort,
        q=q,
        fabric_options=fabric_options,
        selected_fabric_id=fabric_id,
        selected_fabric_name=selected_fabric_name,
        cuts_stats=cuts_stats,
        cuts_have_stock_info=cuts_have_stock_info,
        cuts_have_comment=cuts_have_comment,
        big_cut_threshold=big_cut_threshold,
    )
