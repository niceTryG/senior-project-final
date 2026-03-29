from flask import Blueprint, render_template, make_response, current_app
from flask_login import login_required, current_user

from io import BytesIO
from types import SimpleNamespace
import os
import os
from datetime import datetime
from io import BytesIO

from flask import Blueprint, render_template, make_response, current_app
from flask_login import login_required, current_user

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from ..services.product_service import ProductService

manager_report_bp = Blueprint("manager_report", __name__)

product_service = ProductService()

def _fmt_money(value, currency="UZS"):
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        num = 0.0

    if abs(num - int(num)) < 1e-9:
        formatted = f"{int(num):,}"
    else:
        formatted = f"{num:,.2f}"

    formatted = formatted.replace(",", " ")
    return f"{formatted} {currency}"


def _get_pdf_fonts():
    """
    Register a Cyrillic-capable font for Windows/local dev.
    First tries Windows Arial, then bundled DejaVu in static/fonts.
    """
    regular_candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        os.path.join(current_app.root_path, "static", "fonts", "DejaVuSans.ttf"),
    ]
    bold_candidates = [
        r"C:\Windows\Fonts\arialbd.ttf",
        os.path.join(current_app.root_path, "static", "fonts", "DejaVuSans-Bold.ttf"),
    ]

    regular_path = next((p for p in regular_candidates if os.path.exists(p)), None)
    bold_path = next((p for p in bold_candidates if os.path.exists(p)), None)

    if regular_path:
        pdfmetrics.registerFont(TTFont("MMReportRegular", regular_path))
    if bold_path:
        pdfmetrics.registerFont(TTFont("MMReportBold", bold_path))

    regular_name = "MMReportRegular" if regular_path else "Helvetica"
    bold_name = "MMReportBold" if bold_path else "Helvetica-Bold"

    return regular_name, bold_name
def _empty_manager_report():
    return SimpleNamespace(
        factory_cost_uzs=0,
        shop_sell_uzs=0,
        fabric_value_uzs=0,
        today_sales_uzs=0,
        month_sales_uzs=0,
        month_profit_uzs=0,
        stock_profit_uzs=0,
        stock_profit_usd=0,
        realized_profit_uzs=0,
        transferred_to_shop_uzs=0,
        sold_uzs=0,
        remaining_uzs=0,
        profit_uzs=0,
        low_stock=[],
        product_rows=[],
        products=[],
        unrealized_profit=0,
        realized_profit=0,
    )


def _normalize_manager_report(report):
    if report is None:
        return _empty_manager_report()

    return SimpleNamespace(
        factory_cost_uzs=getattr(report, "factory_cost_uzs", 0) or 0,
        shop_sell_uzs=getattr(report, "shop_sell_uzs", 0) or getattr(report, "transferred_to_shop_uzs", 0) or 0,
        fabric_value_uzs=getattr(report, "fabric_value_uzs", 0) or 0,
        today_sales_uzs=getattr(report, "today_sales_uzs", 0) or 0,
        month_sales_uzs=getattr(report, "month_sales_uzs", 0) or getattr(report, "sold_uzs", 0) or 0,
        month_profit_uzs=getattr(report, "month_profit_uzs", 0) or getattr(report, "profit_uzs", 0) or 0,
        stock_profit_uzs=getattr(report, "stock_profit_uzs", 0) or getattr(report, "unrealized_profit", 0) or 0,
        stock_profit_usd=getattr(report, "stock_profit_usd", 0) or 0,
        realized_profit_uzs=getattr(report, "realized_profit_uzs", 0) or getattr(report, "realized_profit", 0) or 0,
        transferred_to_shop_uzs=getattr(report, "transferred_to_shop_uzs", 0) or getattr(report, "shop_sell_uzs", 0) or 0,
        sold_uzs=getattr(report, "sold_uzs", 0) or getattr(report, "month_sales_uzs", 0) or 0,
        remaining_uzs=getattr(report, "remaining_uzs", 0) or 0,
        profit_uzs=getattr(report, "profit_uzs", 0) or getattr(report, "month_profit_uzs", 0) or 0,
        low_stock=getattr(report, "low_stock", []) or [],
        product_rows=getattr(report, "product_rows", []) or getattr(report, "products", []) or [],
        products=getattr(report, "products", []) or getattr(report, "product_rows", []) or [],
        unrealized_profit=getattr(report, "unrealized_profit", 0) or getattr(report, "stock_profit_uzs", 0) or 0,
        realized_profit=getattr(report, "realized_profit", 0) or getattr(report, "realized_profit_uzs", 0) or 0,
    )


def link_callback(uri, rel):
    """
    Resolve /static/... paths for xhtml2pdf so fonts and images can be loaded.
    """
    if uri.startswith("/static/"):
        return os.path.join(current_app.root_path, uri.lstrip("/").replace("/", os.sep))
    return uri


@manager_report_bp.route("/manager/report")
@login_required
def manager_report():
    factory_id = current_user.factory_id
    raw_report = product_service.get_manager_financial_report(factory_id=factory_id)
    report = _normalize_manager_report(raw_report)
    return render_template("manager/report.html", report=report)


@manager_report_bp.route("/manager/report/pdf")
@login_required
def manager_report_pdf():
    factory_id = current_user.factory_id
    raw_report = product_service.get_manager_financial_report(factory_id=factory_id)
    report = _normalize_manager_report(raw_report)

    regular_font, bold_font = _get_pdf_fonts()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="MMTitle",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
        alignment=TA_LEFT,
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        name="MMSubtitle",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=14,
    )
    section_style = ParagraphStyle(
        name="MMSection",
        parent=styles["Heading2"],
        fontName=bold_font,
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=8,
        spaceAfter=8,
    )
    normal_style = ParagraphStyle(
        name="MMNormal",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#1f2937"),
    )
    small_style = ParagraphStyle(
        name="MMSmall",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#64748b"),
    )
    bold_style = ParagraphStyle(
        name="MMBold",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#0f172a"),
    )

    factory_cost = getattr(report, "factory_cost_uzs", 0) or 0
    shop_value = getattr(report, "shop_sell_uzs", 0) or getattr(report, "transferred_to_shop_uzs", 0) or 0
    fabric_value = getattr(report, "fabric_value_uzs", 0) or 0
    unrealized_profit = getattr(report, "stock_profit_uzs", 0) or getattr(report, "unrealized_profit", 0) or 0
    realized_profit = getattr(report, "realized_profit_uzs", 0) or getattr(report, "realized_profit", 0) or getattr(report, "profit_uzs", 0) or 0
    products = getattr(report, "product_rows", []) or getattr(report, "products", []) or []
    low_stock = getattr(report, "low_stock", []) or []

    total_assets = factory_cost + shop_value + fabric_value

    story = []

    story.append(Paragraph("Финансовый отчёт руководителя", title_style))
    story.append(
        Paragraph(
            f"Сформировано: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            subtitle_style,
        )
    )

    # Summary cards/table
    summary_data = [
        [
            Paragraph("<b>Инвестиции в фабрике</b>", bold_style),
            Paragraph("<b>Стоимость на складе магазина</b>", bold_style),
        ],
        [
            Paragraph(_fmt_money(factory_cost, "UZS"), normal_style),
            Paragraph(_fmt_money(shop_value, "UZS"), normal_style),
        ],
        [
            Paragraph("<b>Стоимость тканей</b>", bold_style),
            Paragraph("<b>Общие активы</b>", bold_style),
        ],
        [
            Paragraph(_fmt_money(fabric_value, "UZS"), normal_style),
            Paragraph(_fmt_money(total_assets, "UZS"), normal_style),
        ],
        [
            Paragraph("<b>Потенциальная прибыль</b>", bold_style),
            Paragraph("<b>Полученная прибыль</b>", bold_style),
        ],
        [
            Paragraph(_fmt_money(unrealized_profit, "UZS"), normal_style),
            Paragraph(_fmt_money(realized_profit, "UZS"), normal_style),
        ],
    ]

    summary_table = Table(summary_data, colWidths=[90 * mm, 90 * mm])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fbff")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#dbe3ef")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe3ef")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )

    story.append(summary_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("Краткий управленческий вывод", section_style))
    story.append(
        Paragraph(
            f"Текущая стоимость активов по отчёту составляет <b>{_fmt_money(total_assets, 'UZS')}</b>. "
            f"Нереализованный потенциал прибыли в остатках — <b>{_fmt_money(unrealized_profit, 'UZS')}</b>. "
            f"Уже полученная прибыль по продажам — <b>{_fmt_money(realized_profit, 'UZS')}</b>.",
            normal_style,
        )
    )
    story.append(Spacer(1, 8))

    

    story.append(Paragraph("Детали по каждому товару", section_style))

    if products:
        product_data = [
            [
                Paragraph("<b>Название</b>", small_style),
                Paragraph("<b>Фабрика</b>", small_style),
                Paragraph("<b>Магазин</b>", small_style),
                Paragraph("<b>Себестоимость</b>", small_style),
                Paragraph("<b>Цена продажи</b>", small_style),
                Paragraph("<b>Потенц. прибыль</b>", small_style),
                Paragraph("<b>Продано</b>", small_style),
                Paragraph("<b>Получ. прибыль</b>", small_style),
            ]
        ]

        for p in products:
            product_data.append(
                [
                    Paragraph(str(p.get("name", "")), small_style),
                    Paragraph(str(p.get("factory_qty", 0)), small_style),
                    Paragraph(str(p.get("shop_qty", 0)), small_style),
                    Paragraph(_fmt_money(p.get("cost_price", 0), "UZS"), small_style),
                    Paragraph(_fmt_money(p.get("sell_price", 0), "UZS"), small_style),
                    Paragraph(_fmt_money(p.get("potential_profit", 0), "UZS"), small_style),
                    Paragraph(str(p.get("sold_units", 0)), small_style),
                    Paragraph(_fmt_money(p.get("realized_profit", 0), "UZS"), small_style),
                ]
            )

        product_table = Table(
            product_data,
            repeatRows=1,
            colWidths=[34 * mm, 16 * mm, 16 * mm, 24 * mm, 24 * mm, 26 * mm, 14 * mm, 26 * mm],
        )
        product_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4ff")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#334155")),
                    ("FONTNAME", (0, 0), (-1, 0), bold_font),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#dbe3ef")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(product_table)
    else:
        story.append(Paragraph("Нет данных по товарам для отображения в отчёте.", normal_style))

    story.append(Spacer(1, 10))
    story.append(Paragraph("Mini Moda — manager report", small_style))

    doc.build(story)

    pdf = buffer.getvalue()
    buffer.close()

    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=manager_report.pdf"
    return response