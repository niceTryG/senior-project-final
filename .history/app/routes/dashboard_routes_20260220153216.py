from flask import Blueprint, render_template, session
from flask_login import login_required, current_user

from datetime import datetime
from ..extensions import db
from ..services.fabric_service import FabricService
from ..services.product_service import ProductService
from ..models import CashRecord, ShopOrder
from datetime import date
from sqlalchemy import func
from app.models import Production, Product
from app.extensions import db

main_bp = Blueprint("main", __name__)
fabric_service = FabricService()
product_service = ProductService()


RU_MONTHS = {
    "January": "января",
    "February": "февраля",
    "March": "марта",
    "April": "апреля",
    "May": "мая",
    "June": "июня",
    "July": "июля",
    "August": "августа",
    "September": "сентября",
    "October": "октября",
    "November": "ноября",
    "December": "декабря",
}

UZ_MONTHS = {
    "January": "yanvar",
    "February": "fevral",
    "March": "mart",
    "April": "aprel",
    "May": "may",
    "June": "iyun",
    "July": "iyul",
    "August": "avgust",
    "September": "sentabr",
    "October": "oktyabr",
    "November": "noyabr",
    "December": "dekabr",
}


def _get_current_date_for_lang():
    """Return current date string formatted according to selected language."""
    now = datetime.now()
    day = now.strftime("%d")
    year = now.strftime("%Y")
    eng_month = now.strftime("%B")

    lang = session.get("lang_code", "ru")

    if lang == "ru":
        month = RU_MONTHS.get(eng_month, eng_month)
    elif lang == "uz":
        month = UZ_MONTHS.get(eng_month, eng_month)
    else:
        month = eng_month

    return f"{day} {month} {year}"


def _calc_cash_totals(factory_id: int):
    """Sum cash by currency directly from CashRecord for this factory."""
    records = CashRecord.query.filter_by(factory_id=factory_id).all()
    total_uzs = sum(r.amount for r in records if r.currency == "UZS")
    total_usd = sum(r.amount for r in records if r.currency == "USD")
    return total_uzs, total_usd


def _build_admin_dashboard_data(factory_id: int):
    """Full overview for Dad (manager/owner) — Uses YESTERDAY + LAST WEEK."""

    # ---- FABRICS ----
    fabric_stats = fabric_service.get_dashboard_stats(factory_id=factory_id)
    usd_uzs_rate = fabric_stats["usd_uzs_rate"]

    # ---- PRODUCTS (FACTORY + SHOP) ----
    factory_uzs, factory_usd = product_service.total_stock_value(factory_id=factory_id)
    shop_uzs, shop_usd = product_service.shop_stock_totals(factory_id=factory_id)

    total_products_uzs = factory_uzs + shop_uzs
    total_products_usd = factory_usd + shop_usd

    # ---- SALES / PRODUCTION ----
    sales = product_service.sales_totals(factory_id=factory_id)
    production = product_service.production_stats(factory_id=factory_id)
    low_stock_products = product_service.get_low_stock_products(factory_id=factory_id)

    yesterday_uzs = sales["yesterday"].get("UZS", 0.0)
    last_week_uzs = sales["last_week"].get("UZS", 0.0)

    # ---- CASH ----
    cash_total_uzs, cash_total_usd = _calc_cash_totals(factory_id=factory_id)

    if usd_uzs_rate:
        cash_total_uzs_equiv = cash_total_uzs + cash_total_usd * usd_uzs_rate
        fabrics_uzs_equiv = fabric_stats["total_value_uzs_equiv"] or 0.0
        business_total_uzs_equiv = (
            cash_total_uzs_equiv
            + total_products_uzs
            + fabrics_uzs_equiv
        )
    else:
        cash_total_uzs_equiv = None
        business_total_uzs_equiv = None

    stats = {
        # ---- fabrics ----
        "fabric_total_fabrics": fabric_stats["total_fabrics"],
        "fabric_low_stock_count": fabric_stats["low_stock_count"],
        "fabric_total_value_uzs": fabric_stats["total_value_uzs"],
        "fabric_total_value_usd": fabric_stats["total_value_usd"],
        "fabric_total_value_uzs_equiv": fabric_stats["total_value_uzs_equiv"],
        "usd_uzs_rate": usd_uzs_rate,

        # ---- products ----
        "factory_stock_uzs": factory_uzs,
        "factory_stock_usd": factory_usd,
        "shop_stock_uzs": shop_uzs,
        "shop_stock_usd": shop_usd,
        "product_total_value_uzs": total_products_uzs,
        "product_total_value_usd": total_products_usd,

        # ---- sales (YESTERDAY + LAST WEEK) ----
        "yesterday_sales_uzs": yesterday_uzs,
        "week_sales_uzs": last_week_uzs,

        # ---- production ----
        "produced_today": production["total_today"],
        "produced_total": production["total_all"],

        # ---- cash ----
        "cash_total_uzs": cash_total_uzs,
        "cash_total_usd": cash_total_usd,
        "cash_total_uzs_equiv": cash_total_uzs_equiv,

        # ---- business total ----
        "business_total_uzs_equiv": business_total_uzs_equiv,
    }

    return {
        "stats": stats,
        "low_stock_products": low_stock_products,
        "factory_uzs": factory_uzs,
        "shop_uzs": shop_uzs,
        "total_uzs": total_products_uzs,
        "usd_uzs_rate": usd_uzs_rate,
    }


def _build_shop_dashboard_data(factory_id: int):
    """Dashboard for Uncle (shop manager). Focus on shop + sales."""
    shop_uzs, shop_usd = product_service.shop_stock_totals(factory_id=factory_id)
    sales = product_service.sales_totals(factory_id=factory_id)

    yesterday_uzs = sales["yesterday"].get("UZS", 0.0)
    last_week_uzs = sales["last_week"].get("UZS", 0.0)

    stocks = product_service.list_shop_stock(factory_id=factory_id)
    total_items = sum(s.quantity or 0 for s in stocks)

    fabric_stats = fabric_service.get_dashboard_stats(factory_id=factory_id)

    stats = {
        "shop_stock_uzs": shop_uzs,
        "shop_stock_usd": shop_usd,
        "yesterday_sales_uzs": yesterday_uzs,
        "week_sales_uzs": last_week_uzs,
        "shop_total_items": total_items,
    }

    return {
        "stats": stats,
        "usd_uzs_rate": fabric_stats["usd_uzs_rate"],
    }


def _build_accountant_dashboard_data(factory_id: int):
    """Dashboard for Mum (accountant/production). Focus on fabric + production."""
    fabric_stats = fabric_service.get_dashboard_stats(factory_id=factory_id)
    production = product_service.production_stats(factory_id=factory_id)

    stats = {
        "fabric_total_fabrics": fabric_stats["total_fabrics"],
        "fabric_total_value_uzs": fabric_stats["total_value_uzs"],
        "fabric_total_value_usd": fabric_stats["total_value_usd"],
        "fabric_total_value_uzs_equiv": fabric_stats["total_value_uzs_equiv"],
        "usd_uzs_rate": fabric_stats["usd_uzs_rate"],
        "fabric_low_stock_count": fabric_stats["low_stock_count"],
        "produced_today": production["total_today"],
        "produced_total": production["total_all"],
    }

    return {
        "stats": stats,
        "usd_uzs_rate": fabric_stats["usd_uzs_rate"],
    }


@main_bp.route("/")
@login_required
def dashboard():
    role = getattr(current_user, "role", "manager")
    factory_id = current_user.factory_id

    # orders counters only for this factory
    pending = (
        ShopOrder.query
        .filter_by(factory_id=factory_id, status="pending")
        .count()
    )
    ready = (
        ShopOrder.query
        .filter_by(factory_id=factory_id, status="ready")
        .count()
    )

    current_date = _get_current_date_for_lang()

    if role == "shop" or current_user.is_shop:
        data = _build_shop_dashboard_data(factory_id=factory_id)
        data["shop_orders_pending"] = pending
        data["shop_orders_ready"] = ready
        data["current_date"] = current_date
        return render_template("dashboard_shop.html", **data)

    elif role == "accountant":
        data = _build_accountant_dashboard_data(factory_id=factory_id)
        data["current_date"] = current_date
        return render_template("dashboard_accountant.html", **data)

    elif role == "manager":
        data = _build_admin_dashboard_data(factory_id=factory_id)
        data["shop_orders_pending"] = pending
        data["shop_orders_ready"] = ready
        data["current_date"] = current_date
        return render_template("dashboard_manager.html", **data)

    else:
        # Admin / default
        data = _build_admin_dashboard_data(factory_id=factory_id)
        data["shop_orders_pending"] = pending
        data["shop_orders_ready"] = ready
        data["current_date"] = current_date
        return render_template("dashboard.html", **data)
