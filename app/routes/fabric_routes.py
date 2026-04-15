from app.telegram_notify import send_telegram_message, send_telegram_document
from app.telegram_config import LOW_STOCK_THRESHOLD  # or hardcode for now (e.g., 3)
from app import db
from ..models import Fabric, Material, Cut, SupplierReceipt, OperationalTask


from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    Response,
    send_file,
    flash,
)
from flask_login import login_required, current_user

from io import BytesIO
from datetime import datetime, timedelta
from urllib.parse import urlencode
from sqlalchemy import or_
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from ..auth_utils import roles_required
from ..services.material_service import MaterialService


fabrics_bp = Blueprint("fabrics", __name__, url_prefix="/materials")
legacy_fabrics_bp = Blueprint("legacy_fabrics", __name__, url_prefix="/fabrics")
service = MaterialService()


@legacy_fabrics_bp.route("/", defaults={"subpath": ""}, methods=["GET", "POST"])
@legacy_fabrics_bp.route("/<path:subpath>", methods=["GET", "POST"])
def legacy_fabrics_redirect(subpath: str):
    query_string = urlencode(request.args, doseq=True)
    destination = f"/materials/{subpath}" if subpath else "/materials/"
    if query_string:
        destination = f"{destination}?{query_string}"
    return redirect(destination, code=307 if request.method == "POST" else 302)


def _supplier_receipt_filename(receipt: SupplierReceipt) -> str:
    safe_supplier = "".join(ch if ch.isalnum() else "_" for ch in (receipt.supplier_name or "supplier")).strip("_") or "supplier"
    return f"supplier_receipt_{receipt.id}_{safe_supplier}.pdf"


def _build_supplier_receipt_pdf(receipt: SupplierReceipt) -> BytesIO:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReceiptTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#14213d"),
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="ReceiptKicker",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=colors.HexColor("#0f766e"),
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="ReceiptMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#6b7280"),
    ))
    styles.add(ParagraphStyle(
        name="CellLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=colors.HexColor("#6b7280"),
    ))
    styles.add(ParagraphStyle(
        name="CellValue",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#14213d"),
    ))
    styles.add(ParagraphStyle(
        name="ValueRight",
        parent=styles["CellValue"],
        alignment=TA_RIGHT,
    ))

    payment_label = (receipt.payment_status or "unpaid").title()
    received_label = receipt.received_at.strftime("%Y-%m-%d") if receipt.received_at else "-"
    unit_cost_label = (
        f"{float(receipt.unit_cost or 0):,.2f} {receipt.currency or ''}"
        if receipt.unit_cost is not None else "-"
    )
    line_total_label = (
        f"{float(receipt.line_total or 0):,.2f} {receipt.currency or ''}"
        if receipt.line_total is not None else "-"
    )
    recorded_by = (
        getattr(receipt.created_by, "username", None)
        or str(receipt.created_by_id or "-")
    )

    story = []
    story.append(Paragraph("ADRAS SUPPLY DESK", styles["ReceiptKicker"]))
    story.append(Paragraph("Supplier Receipt", styles["ReceiptTitle"]))
    story.append(Paragraph(
        "Official receiving document generated from the Adras supplier delivery ledger.",
        styles["ReceiptMeta"],
    ))
    story.append(Spacer(1, 8))

    header_table = Table([
        [
            Paragraph(
                "<b>Supplier</b><br/>"
                f"{receipt.supplier_name or '-'}<br/>"
                f"<font color='#6b7280'>Recorded by: {recorded_by}</font>",
                styles["CellValue"],
            ),
            Paragraph(
                f"<b>Receipt ID</b><br/>#{receipt.id}<br/>"
                f"<font color='#6b7280'>Received: {received_label}</font>",
                styles["ValueRight"],
            ),
        ]
    ], colWidths=[110 * mm, 64 * mm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#dbe4ea")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe4ea")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))

    info_table = Table([
        [
            Paragraph("<b>Invoice number</b><br/>" + (receipt.invoice_number or "-"), styles["CellValue"]),
            Paragraph("<b>Payment status</b><br/>" + payment_label, styles["CellValue"]),
            Paragraph("<b>Currency</b><br/>" + (receipt.currency or "-"), styles["CellValue"]),
        ]
    ], colWidths=[58 * mm, 58 * mm, 58 * mm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e5e7eb")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 12))

    line_items = Table([
        ["Material", "Qty", "Unit Cost", "Line Total"],
        [
            receipt.material_name or "-",
            f"{float(receipt.quantity_received or 0):,.2f} {receipt.unit or ''}",
            unit_cost_label,
            line_total_label,
        ],
    ], colWidths=[78 * mm, 34 * mm, 34 * mm, 38 * mm])
    line_items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6fffb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#134e4a")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(line_items)
    story.append(Spacer(1, 12))

    totals_table = Table([
        ["Subtotal", line_total_label],
        ["Payment", payment_label],
    ], colWidths=[118 * mm, 66 * mm])
    totals_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffdf8")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e5d5c6")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5d5c6")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(totals_table)

    if receipt.note:
        story.append(Spacer(1, 12))
        note_table = Table([
            [Paragraph(f"<b>Note</b><br/>{receipt.note}", styles["ReceiptMeta"])]
        ], colWidths=[184 * mm])
        note_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#faf5ef")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e5d5c6")),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(note_table)

    story.append(Spacer(1, 18))
    signatures = Table([
        ["Received by", "Supplier signature"],
        ["", ""],
    ], colWidths=[92 * mm, 92 * mm])
    signatures.setStyle(TableStyle([
        ("LINEABOVE", (0, 1), (0, 1), 1, colors.HexColor("#94a3b8")),
        ("LINEABOVE", (1, 1), (1, 1), 1, colors.HexColor("#94a3b8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#6b7280")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
    ]))
    story.append(signatures)
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Generated from the Adras supplier receipt ledger for print, PDF export, and Telegram sharing.",
        styles["ReceiptMeta"],
    ))

    doc.build(story)
    buf.seek(0)
    return buf


def _receipt_redirect_target(receipt: SupplierReceipt):
    return redirect(url_for("fabrics.supplier_detail", supplier_name=receipt.supplier_name))


@fabrics_bp.route("/", methods=["GET"], endpoint="list")
@login_required
def list_materials():
    """Список материалов с фильтрами и пагинацией."""
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "name")
    selected_category = (request.args.get("category") or "").strip()
    selected_material_type = (request.args.get("material_type") or "").strip().lower()
    selected_stock_state = (request.args.get("stock_state") or "").strip().lower()
    selected_supplier_name = (request.args.get("supplier_name") or "").strip()
    category = selected_category or None
    page = request.args.get("page", 1, type=int)

    factory_id = current_user.factory_id

    per_page = 5
    materials, pagination = service.search_materials(
        query=q or None,
        sort=sort,
        category=category,
        material_type=selected_material_type or None,
        stock_state=selected_stock_state or None,
        supplier_name=selected_supplier_name or None,
        page=page,
        per_page=per_page,
        factory_id=factory_id,
    )

    # Build summary/chart data from the full filtered dataset, not current page only.
    materials_for_insights, _ = service.search_materials(
        query=q or None,
        sort=sort,
        category=category,
        material_type=selected_material_type or None,
        stock_state=selected_stock_state or None,
        supplier_name=selected_supplier_name or None,
        factory_id=factory_id,
    )

    any_low_stock = service.any_low_stock(materials_for_insights)
    cuts = service.recent_cuts(factory_id=factory_id)
    categories = service.get_categories(factory_id=factory_id)
    material_types = service.get_material_types(factory_id=factory_id)
    suppliers = service.get_suppliers(factory_id=factory_id)

    # курс для мелкого текста (если используешь)
    fabric_stats = service.get_dashboard_stats(factory_id=factory_id)
    usd_uzs_rate = fabric_stats.get("usd_uzs_rate")

    material_mix = service.summarize_material_mix(materials_for_insights)

    # --------------------------------------------------
    # CHART 1: OVERVIEW VS SELECTED TYPE
    # --------------------------------------------------
    chart_palette = [
        "#2563eb",
        "#14b8a6",
        "#f59e0b",
        "#8b5cf6",
        "#ef4444",
        "#0ea5e9",
        "#22c55e",
        "#f97316",
        "#6366f1",
        "#84cc16",
    ]

    if selected_material_type:
        chart_mode = "type_top"
        same_type = [
            f for f in materials_for_insights
            if str(getattr(f, "material_type", "") or "").strip().lower() == selected_material_type
        ]

        units_by_type: dict[str, int] = {}
        for item in same_type:
            unit_key = str(getattr(item, "unit", None) or "-").strip().lower()
            units_by_type[unit_key] = units_by_type.get(unit_key, 0) + 1

        chart_unit = None
        if units_by_type:
            chart_unit = max(units_by_type.items(), key=lambda pair: pair[1])[0]

        filtered_same_unit = [
            f for f in same_type
            if (str(getattr(f, "unit", None) or "-").strip().lower() == chart_unit)
        ] if chart_unit else same_type

        materials_for_chart = sorted(
            filtered_same_unit,
            key=lambda f: float(f.quantity or 0),
            reverse=True
        )[:10]

        fabric_chart_labels = [
            f.name + (f" ({f.color})" if f.color else "")
            for f in materials_for_chart
        ]
        fabric_chart_quantities = [
            float(f.quantity or 0)
            for f in materials_for_chart
        ]
        fabric_chart_colors = chart_palette[:len(fabric_chart_quantities)]
        chart_title = f"Top {selected_material_type.replace('_', ' ').title()} materials"
        if chart_unit:
            chart_subtitle = f"Highest on-hand quantities for this type, limited to the dominant unit ({chart_unit})."
        else:
            chart_subtitle = "Highest on-hand quantities for this selected material type."
    else:
        chart_mode = "type_mix"
        counts_by_type = material_mix.get("counts_by_type") or {}
        sorted_mix = sorted(
            counts_by_type.items(),
            key=lambda pair: pair[1],
            reverse=True,
        )
        fabric_chart_labels = [material_type.replace("_", " ").title() for material_type, _count in sorted_mix]
        fabric_chart_quantities = [int(count) for _material_type, count in sorted_mix]
        fabric_chart_colors = chart_palette[:len(fabric_chart_quantities)]
        chart_title = "Material mix by type"
        chart_subtitle = "Use the type chips to drill into a top-10 chart for one category."

    # --------------------------------------------------
    # CHART 2: RECENT CUTS USAGE
    # --------------------------------------------------
    recent_cuts_for_chart = cuts[:8]

    fabric_cut_chart_labels = [
        c.fabric.name if c.fabric else f"ID {c.fabric_id}"
        for c in recent_cuts_for_chart
    ]
    fabric_cut_chart_values = [
        float(c.used_amount or 0)
        for c in recent_cuts_for_chart
    ]

    return render_template(
        "fabrics/list.html",
        fabrics=materials,
        pagination=pagination,
        any_low_stock=any_low_stock,
        q=q,
        sort=sort,
        categories=categories,
        material_types=material_types,
        selected_category=selected_category,
        selected_material_type=selected_material_type,
        selected_stock_state=selected_stock_state,
        selected_supplier_name=selected_supplier_name,
        suppliers=suppliers,
        cuts=cuts,
        LOW_STOCK_THRESHOLD=MaterialService.LOW_STOCK_THRESHOLD,
        usd_uzs_rate=usd_uzs_rate,
        material_mix=material_mix,

        # chart data
        chart_mode=chart_mode,
        chart_title=chart_title,
        chart_subtitle=chart_subtitle,
        fabric_chart_labels=fabric_chart_labels,
        fabric_chart_quantities=fabric_chart_quantities,
        fabric_chart_colors=fabric_chart_colors,
        fabric_cut_chart_labels=fabric_cut_chart_labels,
        fabric_cut_chart_values=fabric_cut_chart_values,
    )

@fabrics_bp.route("/add", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def add():
    """Добавление ткани (с умным merge-предложением)."""
    name = (request.form.get("name") or "").strip()
    color = (request.form.get("color") or "").strip() or None
    material_type = (request.form.get("material_type") or "fabric").strip() or "fabric"
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
    supplier_name = (request.form.get("supplier_name") or "").strip() or None
    min_stock_raw = (request.form.get("min_stock_quantity") or "").strip()
    min_stock_quantity = None
    if min_stock_raw:
        try:
            min_stock_quantity = float(min_stock_raw)
        except ValueError:
            min_stock_quantity = None

    status, data = service.add_or_suggest_merge(
        factory_id=current_user.factory_id,
        name=name,
        color=color,
        unit=unit,
        quantity=quantity,
        price_per_unit=price_per_unit,
        price_currency=price_currency,
        category=category,
        material_type=material_type,
        min_stock_quantity=min_stock_quantity,
        supplier_name=supplier_name,
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
    material_type = (request.form.get("material_type") or "fabric").strip() or "fabric"
    supplier_name = (request.form.get("supplier_name") or "").strip() or None
    min_stock_raw = (request.form.get("min_stock_quantity") or "").strip()
    min_stock_quantity = None
    if min_stock_raw:
        try:
            min_stock_quantity = float(min_stock_raw)
        except ValueError:
            min_stock_quantity = None

    service.confirm_merge(
        factory_id=current_user.factory_id,
        existing_id=existing_id,
        quantity=quantity,
        price_per_unit=price_per_unit,
        price_currency=price_currency,
        category=category,
        material_type=material_type,
        min_stock_quantity=min_stock_quantity,
        supplier_name=supplier_name,
    )

    return redirect(url_for("fabrics.list"))


@fabrics_bp.route("/create_new", methods=["POST"], endpoint="create_new")
@login_required
@roles_required("admin", "manager")
def create_new_material():
    """Создать новую ткань, даже если сервис предлагал merge."""
    name = (request.form.get("name") or "").strip()
    color = (request.form.get("color") or "").strip() or None
    material_type = (request.form.get("material_type") or "fabric").strip() or "fabric"
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
    supplier_name = (request.form.get("supplier_name") or "").strip() or None
    min_stock_raw = (request.form.get("min_stock_quantity") or "").strip()
    min_stock_quantity = None
    if min_stock_raw:
        try:
            min_stock_quantity = float(min_stock_raw)
        except ValueError:
            min_stock_quantity = None

    service.create_material(
        factory_id=current_user.factory_id,
        name=name,
        color=color,
        unit=unit,
        quantity=quantity,
        price_per_unit=price_per_unit,
        price_currency=price_currency,
        category=category,
        material_type=material_type,
        min_stock_quantity=min_stock_quantity,
        supplier_name=supplier_name,
    )

    return redirect(url_for("fabrics.list"))


@fabrics_bp.route("/<int:fabric_id>/cut", methods=["POST"], endpoint="cut")
@login_required
@roles_required("admin", "manager")
def cut_material_route(fabric_id: int):
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
    service.cut_material(
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


@fabrics_bp.route("/cuts/new", methods=["GET"], endpoint="cuts_new")
@login_required
@roles_required("admin", "manager")
def material_cuts_new():
    materials = (
        Material.query
        .filter(Material.factory_id == current_user.factory_id)
        .order_by(Material.name.asc(), Material.color.asc())
        .all()
    )
    selected_fabric_id = request.args.get("fabric_id", type=int)
    selected_fabric = None
    if selected_fabric_id:
        selected_fabric = next((row for row in materials if row.id == selected_fabric_id), None)

    return render_template(
        "fabrics/cut_form.html",
        fabrics=materials,
        selected_fabric=selected_fabric,
        today_value=datetime.utcnow().date().isoformat(),
    )


@fabrics_bp.route("/cuts/create", methods=["POST"], endpoint="cuts_create")
@login_required
@roles_required("admin", "manager")
def material_cuts_create():
    fabric_id = request.form.get("fabric_id", type=int)
    used_raw = (request.form.get("used_amount") or "").strip()
    cut_date_raw = (request.form.get("cut_date") or "").strip()
    comment = (request.form.get("comment") or "").strip() or None

    try:
        used_amount = float(used_raw)
    except ValueError:
        used_amount = 0.0

    cut_date_value = datetime.utcnow().date()
    if cut_date_raw:
        try:
            cut_date_value = datetime.strptime(cut_date_raw, "%Y-%m-%d").date()
        except ValueError:
            cut_date_value = datetime.utcnow().date()

    cut_row = service.cut_material(
        factory_id=current_user.factory_id,
        fabric_id=fabric_id,
        used_amount=used_amount,
        cut_date=cut_date_value,
        comment=comment,
        created_by_id=current_user.id,
    )
    if not cut_row:
        flash("Cut could not be recorded. Check the material and available stock.", "danger")
        return redirect(url_for("fabrics.cuts_new", fabric_id=fabric_id))

    fabric = Fabric.query.filter_by(id=fabric_id, factory_id=current_user.factory_id).first()
    if fabric:
        remaining = float(fabric.quantity or 0)
        try:
            if remaining <= LOW_STOCK_THRESHOLD:
                send_telegram_message(
                    "Low material alert\n"
                    f"Name: {fabric.name}\n"
                    f"Remaining: {remaining:.2f} {fabric.unit}\n"
                    f"Color: {fabric.color or '-'}"
                )
        except Exception:
            pass

    flash("Cut operation recorded.", "success")
    return redirect(url_for("fabrics.cuts_history"))


@fabrics_bp.route("/export", methods=["GET"], endpoint="export")
@login_required
@roles_required("admin", "manager")
def export_materials():
    """Экспорт всех тканей фабрики в CSV."""
    q = (request.args.get("q") or "").strip() or None
    category = (request.args.get("category") or "").strip() or None
    material_type = (request.args.get("material_type") or "").strip().lower() or None
    stock_state = (request.args.get("stock_state") or "").strip().lower() or None
    supplier_name = (request.args.get("supplier_name") or "").strip() or None

    csv_bytes = service.export_materials_csv(
        factory_id=current_user.factory_id,
        query=q,
        category=category,
        material_type=material_type,
        stock_state=stock_state,
        supplier_name=supplier_name,
    )
    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=fabrics.csv"},
    )


@fabrics_bp.route("/suppliers/view", methods=["GET"])
@login_required
def supplier_detail():
    supplier_name = (request.args.get("supplier_name") or "").strip()
    if not supplier_name:
        return redirect(url_for("fabrics.list"))

    snapshot = service.get_supplier_snapshot(
        supplier_name=supplier_name,
        factory_id=current_user.factory_id,
    )

    return render_template(
        "fabrics/supplier_detail.html",
        supplier_name=supplier_name,
        snapshot=snapshot,
        LOW_STOCK_THRESHOLD=MaterialService.LOW_STOCK_THRESHOLD,
    )


@fabrics_bp.route("/suppliers/statement", methods=["GET"])
@login_required
def supplier_statement():
    supplier_name = (request.args.get("supplier_name") or "").strip()
    if not supplier_name:
        return redirect(url_for("fabrics.list"))

    statement = service.get_supplier_statement(
        supplier_name=supplier_name,
        factory_id=current_user.factory_id,
    )

    return render_template(
        "fabrics/supplier_statement.html",
        supplier_name=supplier_name,
        statement=statement,
        LOW_STOCK_THRESHOLD=MaterialService.LOW_STOCK_THRESHOLD,
    )


@fabrics_bp.route("/suppliers/receipts", methods=["GET"])
@login_required
def supplier_receipts():
    supplier_name = (request.args.get("supplier_name") or "").strip() or None
    payment_status = (request.args.get("payment_status") or "").strip() or None
    invoice_number = (request.args.get("invoice_number") or "").strip() or None
    q = (request.args.get("q") or "").strip() or None
    date_from_str = (request.args.get("from") or "").strip()
    date_to_str = (request.args.get("to") or "").strip()

    date_from = None
    date_to = None
    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
        except ValueError:
            date_from = None
    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d").date() + timedelta(days=1)
        except ValueError:
            date_to = None

    overview = service.supplier_receipt_overview(
        factory_id=current_user.factory_id,
        supplier_name=supplier_name,
        payment_status=payment_status,
        invoice_number=invoice_number,
        date_from=date_from,
        date_to=date_to,
        q=q,
    )

    return render_template(
        "fabrics/receipt_history.html",
        overview=overview,
        selected_supplier_name=supplier_name or "",
        selected_payment_status=(payment_status or "").strip().lower(),
        selected_invoice_number=invoice_number or "",
        search_query=q or "",
        filter_from=date_from_str,
        filter_to=date_to_str,
    )


@fabrics_bp.route("/suppliers/profile", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def save_supplier_profile():
    supplier_name = (request.form.get("supplier_name") or "").strip()
    if not supplier_name:
        return redirect(url_for("fabrics.list"))

    service.upsert_supplier_profile(
        factory_id=current_user.factory_id,
        supplier_name=supplier_name,
        contact_person=request.form.get("contact_person"),
        phone=request.form.get("phone"),
        telegram_handle=request.form.get("telegram_handle"),
        note=request.form.get("note"),
    )

    return redirect(url_for("fabrics.supplier_detail", supplier_name=supplier_name))


@fabrics_bp.route("/suppliers/statement/export", methods=["GET"])
@login_required
@roles_required("admin", "manager")
def export_supplier_statement():
    supplier_name = (request.args.get("supplier_name") or "").strip()
    if not supplier_name:
        return redirect(url_for("fabrics.list"))

    csv_bytes = service.export_supplier_statement_csv(
        supplier_name=supplier_name,
        factory_id=current_user.factory_id,
    )
    safe_name = supplier_name.replace(" ", "_")
    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=supplier_statement_{safe_name}.csv"},
    )


@fabrics_bp.route("/suppliers/followup-task", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def create_supplier_followup_task():
    supplier_name = (request.form.get("supplier_name") or "").strip()
    if not supplier_name:
        return redirect(url_for("fabrics.list"))

    statement = service.get_supplier_statement(
        supplier_name=supplier_name,
        factory_id=current_user.factory_id,
    )
    snapshot = statement["snapshot"]

    if not snapshot.get("unpaid_count"):
        flash("This supplier has no unpaid receipts to follow up right now.", "info")
        return redirect(url_for("fabrics.supplier_statement", supplier_name=supplier_name))

    profile = snapshot.get("profile")
    if not profile:
        profile = service.upsert_supplier_profile(
            factory_id=current_user.factory_id,
            supplier_name=supplier_name,
        )

    existing_task = (
        OperationalTask.query
        .filter(
            OperationalTask.factory_id == current_user.factory_id,
            OperationalTask.source_type == "supplier_unpaid_followup",
            OperationalTask.source_id == profile.id,
            OperationalTask.status.in_(("open", "in_progress")),
        )
        .first()
    )
    if existing_task:
        flash("A supplier follow-up task is already open for this supplier.", "info")
        return redirect(url_for("fabrics.supplier_statement", supplier_name=supplier_name))

    payable_bits = [
        f"{float(total or 0):.2f} {currency}"
        for currency, total in (snapshot.get("unpaid_by_currency") or {}).items()
    ]
    contact_bits = []
    if getattr(profile, "contact_person", None):
        contact_bits.append(f"contact {profile.contact_person}")
    if getattr(profile, "phone", None):
        contact_bits.append(f"phone {profile.phone}")
    if getattr(profile, "telegram_handle", None):
        contact_bits.append(f"telegram {profile.telegram_handle}")

    description_parts = [f"{int(snapshot.get('unpaid_count') or 0)} unpaid receipt(s) pending."]
    if payable_bits:
        description_parts.append("Open payable: " + ", ".join(payable_bits) + ".")
    if contact_bits:
        description_parts.append("Supplier contact: " + ", ".join(contact_bits) + ".")

    task = OperationalTask(
        factory_id=current_user.factory_id,
        created_by_id=getattr(current_user, "id", None),
        task_type="supplier_followup",
        source_type="supplier_unpaid_followup",
        source_id=profile.id,
        title=f"Follow up unpaid supplier {supplier_name}"[:160],
        description=" ".join(description_parts)[:255],
        action_url=url_for("fabrics.supplier_statement", supplier_name=supplier_name),
        target_role="manager",
        priority="high" if int(snapshot.get("unpaid_count") or 0) >= 2 else "medium",
        status="open",
        due_date=datetime.utcnow().date() + timedelta(days=2),
        is_system_generated=False,
    )
    db.session.add(task)
    db.session.commit()

    flash("Supplier follow-up task created.", "success")
    return redirect(url_for("fabrics.supplier_statement", supplier_name=supplier_name))


@fabrics_bp.route("/suppliers/receive", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def receive_from_supplier():
    supplier_name = (request.form.get("supplier_name") or "").strip()
    fabric_id = request.form.get("fabric_id", type=int)
    quantity_raw = (request.form.get("quantity_received") or "").strip()
    received_at_raw = (request.form.get("received_at") or "").strip()
    note = (request.form.get("note") or "").strip() or None
    unit_cost_raw = (request.form.get("unit_cost") or "").strip()
    currency = (request.form.get("currency") or "").strip() or None
    invoice_number = (request.form.get("invoice_number") or "").strip() or None
    payment_status = (request.form.get("payment_status") or "").strip() or "unpaid"

    try:
        quantity_received = float(quantity_raw)
    except ValueError:
        quantity_received = 0.0

    received_at = None
    if received_at_raw:
        try:
            received_at = datetime.strptime(received_at_raw, "%Y-%m-%d").date()
        except ValueError:
            received_at = None
    if received_at is None:
        received_at = datetime.utcnow().date()

    unit_cost = None
    if unit_cost_raw:
        try:
            unit_cost = float(unit_cost_raw)
        except ValueError:
            unit_cost = None

    ok, message, receipt = service.receive_supplier_material(
        factory_id=current_user.factory_id,
        fabric_id=fabric_id,
        supplier_name=supplier_name,
        quantity_received=quantity_received,
        received_at=received_at,
        created_by_id=current_user.id,
        unit_cost=unit_cost,
        currency=currency,
        invoice_number=invoice_number,
        payment_status=payment_status,
        note=note,
    )

    if ok:
        flash(message, "success")
        if receipt:
            flash("Receipt document is ready from the recent receipts section.", "info")
    else:
        flash(message, "danger")
    return redirect(url_for("fabrics.supplier_detail", supplier_name=supplier_name))


@fabrics_bp.route("/suppliers/receipt/<int:receipt_id>", methods=["GET"])
@login_required
def supplier_receipt_detail(receipt_id: int):
    receipt = service.get_supplier_receipt(
        receipt_id=receipt_id,
        factory_id=current_user.factory_id,
    )
    if not receipt:
        return redirect(url_for("fabrics.list"))

    return render_template(
        "fabrics/supplier_receipt.html",
        receipt=receipt,
    )


@fabrics_bp.route("/suppliers/receipt/<int:receipt_id>/edit", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def supplier_receipt_edit(receipt_id: int):
    receipt = service.get_supplier_receipt(
        receipt_id=receipt_id,
        factory_id=current_user.factory_id,
    )
    if not receipt:
        return redirect(url_for("fabrics.list"))

    quantity_raw = (request.form.get("quantity_received") or "").strip()
    received_at_raw = (request.form.get("received_at") or "").strip()
    unit_cost_raw = (request.form.get("unit_cost") or "").strip()
    currency = (request.form.get("currency") or "").strip() or None
    invoice_number = (request.form.get("invoice_number") or "").strip() or None
    payment_status = (request.form.get("payment_status") or "").strip() or "unpaid"
    note = (request.form.get("note") or "").strip() or None

    try:
        quantity_received = float(quantity_raw)
    except ValueError:
        quantity_received = 0.0

    received_at = receipt.received_at
    if received_at_raw:
        try:
            received_at = datetime.strptime(received_at_raw, "%Y-%m-%d").date()
        except ValueError:
            received_at = receipt.received_at

    unit_cost = None
    if unit_cost_raw:
        try:
            unit_cost = float(unit_cost_raw)
        except ValueError:
            unit_cost = None

    ok, message, updated_receipt = service.update_supplier_receipt(
        receipt_id=receipt_id,
        factory_id=current_user.factory_id,
        quantity_received=quantity_received,
        received_at=received_at,
        unit_cost=unit_cost,
        currency=currency,
        invoice_number=invoice_number,
        payment_status=payment_status,
        note=note,
    )
    flash(message, "success" if ok else "danger")
    target = updated_receipt or receipt
    return redirect(url_for("fabrics.supplier_receipt_detail", receipt_id=target.id))


@fabrics_bp.route("/suppliers/receipt/<int:receipt_id>/pdf", methods=["GET"])
@login_required
def supplier_receipt_pdf(receipt_id: int):
    receipt = service.get_supplier_receipt(
        receipt_id=receipt_id,
        factory_id=current_user.factory_id,
    )
    if not receipt:
        return redirect(url_for("fabrics.list"))

    pdf_buffer = _build_supplier_receipt_pdf(receipt)
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=_supplier_receipt_filename(receipt),
        mimetype="application/pdf",
    )


@fabrics_bp.route("/suppliers/receipt/<int:receipt_id>/telegram", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def supplier_receipt_send_telegram(receipt_id: int):
    receipt = service.get_supplier_receipt(
        receipt_id=receipt_id,
        factory_id=current_user.factory_id,
    )
    if not receipt:
        return redirect(url_for("fabrics.list"))

    pdf_buffer = _build_supplier_receipt_pdf(receipt)
    send_telegram_document(
        pdf_buffer.getvalue(),
        _supplier_receipt_filename(receipt),
        caption=(
            f"<b>Supplier receipt #{receipt.id}</b>\n"
            f"Supplier: <b>{receipt.supplier_name}</b>\n"
            f"Material: <b>{receipt.material_name}</b>\n"
            f"Qty: <b>{float(receipt.quantity_received or 0):.2f} {receipt.unit or ''}</b>"
        ),
        factory_id=current_user.factory_id,
        include_manager_chats=True,
    )
    flash("Receipt PDF sent to linked Telegram chats.", "success")
    return _receipt_redirect_target(receipt)


@fabrics_bp.route("/suppliers/receipt-status", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def update_supplier_receipt_status():
    receipt_id = request.form.get("receipt_id", type=int)
    supplier_name = (request.form.get("supplier_name") or "").strip()
    payment_status = (request.form.get("payment_status") or "").strip()

    ok, message, receipt = service.update_supplier_receipt_status(
        receipt_id=receipt_id,
        factory_id=current_user.factory_id,
        payment_status=payment_status,
    )

    supplier_name = supplier_name or (receipt.supplier_name if receipt else "")
    if supplier_name:
        return redirect(url_for("fabrics.supplier_detail", supplier_name=supplier_name))
    return redirect(url_for("fabrics.list"))


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
        f"Type: {getattr(fabric, 'material_type', 'fabric')}\n"
        f"Color: {fabric.color}\n"
        f"Unit: {fabric.unit}\n"
        f"Qty: {fabric.quantity}\n"
        f"Min stock: {getattr(fabric, 'min_stock_quantity', '')}\n"
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
    from datetime import date as date_type

    date_from_str = (request.args.get("from") or "").strip()
    date_to_str = (request.args.get("to") or "").strip()
    preset = (request.args.get("preset") or "").strip()
    sort = (request.args.get("sort") or "date_desc").strip()
    material_id = request.args.get("material_id", type=int) or request.args.get("fabric_id", type=int)
    selected_material_type = (request.args.get("material_type") or "").strip().lower()
    q = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 25

    date_from = None
    date_to = None
    date_format = "%Y-%m-%d"
    today = date_type.today()

    if not date_from_str and not date_to_str:
        if not preset:
            preset = "last_7"
        if preset == "last_7":
            date_from = today - timedelta(days=6)
            date_to = today
        elif preset == "this_month":
            date_from = today.replace(day=1)
            date_to = today
        elif preset == "last_month":
            first_this_month = today.replace(day=1)
            last_prev_month = first_this_month - timedelta(days=1)
            date_from = last_prev_month.replace(day=1)
            date_to = last_prev_month
        else:
            preset = "all"
        date_from_str = date_from.strftime(date_format) if date_from else ""
        date_to_str = date_to.strftime(date_format) if date_to else ""
    else:
        preset = "custom"
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

    selected_material = None
    if material_id:
        q_base = q_base.filter(Cut.fabric_id == material_id)
        selected_material = (
            Material.query
            .filter_by(id=material_id, factory_id=current_user.factory_id)
            .first()
        )

    if selected_material_type:
        q_base = q_base.filter(db.func.lower(Fabric.material_type) == selected_material_type)

    if q:
        like = f"%{q.lower()}%"
        q_base = q_base.filter(
            or_(
                db.func.lower(Fabric.name).like(like),
                db.func.lower(db.func.coalesce(Fabric.color, "")).like(like),
                db.func.lower(db.func.coalesce(Fabric.public_id, "")).like(like),
                db.func.lower(db.func.coalesce(Fabric.supplier_name, "")).like(like),
            )
        )

    if sort == "date_asc":
        q_ordered = q_base.order_by(Cut.cut_date.asc(), Cut.id.asc())
    elif sort == "amount_desc":
        q_ordered = q_base.order_by(Cut.used_amount.desc(), Cut.id.desc())
    elif sort == "amount_asc":
        q_ordered = q_base.order_by(Cut.used_amount.asc(), Cut.id.asc())
    elif sort == "material_name":
        q_ordered = q_base.order_by(Fabric.name.asc(), Cut.cut_date.desc(), Cut.id.desc())
    else:
        sort = "date_desc"
        q_ordered = q_base.order_by(Cut.cut_date.desc(), Cut.id.desc())

    pagination = q_ordered.paginate(page=page, per_page=per_page, error_out=False)
    cuts = pagination.items
    visible_cuts = list(cuts)

    cuts_have_stock_info = any(c.remaining_quantity is not None for c in visible_cuts)
    cuts_have_comment = any(bool(c.comment) for c in visible_cuts)
    cuts_have_worker = any(getattr(c, "created_by", None) is not None for c in visible_cuts)

    material_options = (
        Material.query
        .filter(Material.factory_id == current_user.factory_id)
        .order_by(Material.name.asc(), Material.color.asc())
        .all()
    )
    material_types = service.get_material_types(factory_id=current_user.factory_id)

    return render_template(
        "fabrics/cuts.html",
        cuts=cuts,
        pagination=pagination,
        date_from=date_from_str,
        date_to=date_to_str,
        preset=preset,
        sort=sort,
        q=q,
        material_options=material_options,
        material_types=material_types,
        selected_material_id=material_id,
        selected_material_name=(selected_material.name if selected_material else None),
        selected_material_type=selected_material_type,
        cuts_have_stock_info=cuts_have_stock_info,
        cuts_have_comment=cuts_have_comment,
        cuts_have_worker=cuts_have_worker,
    )

@fabrics_bp.route("/usage", methods=["GET"])
@login_required
@roles_required("admin", "manager")
def usage_summary():
    date_from_str = (request.args.get("from") or "").strip()
    date_to_str = (request.args.get("to") or "").strip()
    date_format = "%Y-%m-%d"

    date_from = None
    date_to = None

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

    # use your service summary
    summary = service.get_usage_summary(
        date_from=date_from,
        date_to=date_to,
        factory_id=current_user.factory_id,
    )

    rows = summary["rows"]          # list of {fabric, total_used}
    total_used = summary["total_used"]

    # totals by unit (kg/m etc.)
    totals_by_unit: dict[str, float] = {}
    for r in rows:
        fabric = r["fabric"]
        amount = r["total_used"]
        if not fabric or amount is None:
            continue
        unit = fabric.unit or ""
        totals_by_unit.setdefault(unit, 0.0)
        totals_by_unit[unit] += amount

    # for percentage inside the table, we’ll do share per unit
    totals_by_unit_for_share = totals_by_unit or {}

    # small helper on each row: percent within this unit
    enriched_rows = []
    for r in rows:
        fabric = r["fabric"]
        amount = r["total_used"]
        unit = fabric.unit if fabric else ""
        unit_total = totals_by_unit_for_share.get(unit, 0.0) or 0.0

        if unit_total > 0:
            share_pct = (amount * 100.0) / unit_total
        else:
            share_pct = 0.0

        enriched_rows.append(
            {
                "fabric": fabric,
                "total_used": amount,
                "share_pct": share_pct,
            }
        )

    # sort by total_used desc by default (you can tweak later)
    enriched_rows.sort(key=lambda r: r["total_used"], reverse=True)

    return render_template(
        "fabrics/usage_summary.html",
        rows=enriched_rows,
        totals_by_unit=totals_by_unit,
        total_used=total_used,
        date_from=date_from_str,
        date_to=date_to_str,
    )
