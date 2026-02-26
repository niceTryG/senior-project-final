from datetime import datetime, date, timedelta

from flask import Blueprint, render_template, session, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func

from ..extensions import db
from ..models import CashRecord, Production, Product, Movement, ShopStock
from ..services.product_service import ProductService


main_bp = Blueprint("main", __name__)
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
    records = CashRecord.query.filter_by(factory_id=factory_id).all()
    total_uzs = sum(r.amount for r in records if r.currency == "UZS")
    total_usd = sum(r.amount for r in records if r.currency == "USD")
    return total_uzs, total_usd


def _get_production_today_summary(factory_id: int):
    """
    Returns:
      produced_today_total (pcs)
      produced_today_models (count of models)
      prod_today_rows: list of (name, qty) sorted desc
    """
    today = date.today()

    rows = (
        db.session.query(Product.name, func.coalesce(func.sum(Production.quantity), 0))
        .join(Production, Production.product_id == Product.id)
        .filter(Product.factory_id == factory_id)
        .filter(Production.date == today)
        .group_by(Product.name)
        .order_by(func.sum(Production.quantity).desc())
        .all()
    )

    produced_today_total = int(sum(qty for _, qty in rows) or 0)
    produced_today_models = int(len(rows))
    return produced_today_total, produced_today_models, rows


def _get_shop_low_stock(factory_id: int, threshold: int = 5, limit: int = 3):
    """
    Low stock in SHOP (not factory).
    Returns:
      count_low
      top_items: list of dicts {id, name, qty}
    """
    rows = (
        ShopStock.query
        .join(Product, Product.id == ShopStock.product_id)
        .filter(Product.factory_id == factory_id)
        .filter(ShopStock.quantity < threshold)
        .order_by(ShopStock.quantity.asc(), Product.name.asc())
        .all()
    )

    top_items = [
        {"id": r.product_id, "name": r.product.name, "qty": int(r.quantity or 0)}
        for r in rows[:limit]
    ]
    return len(rows), top_items


def _get_yesterday_transfer_total(factory_id: int):
    """
    Yesterday factory ➜ shop transfer total pcs.
    Uses legacy Movement (you already log it in multiple places).
    """
    y = date.today() - timedelta(days=1)
    start = datetime(y.year, y.month, y.day, 0, 0, 0)
    end = start + timedelta(days=1)

    total = (
        db.session.query(func.coalesce(func.sum(Movement.change), 0))
        .filter(Movement.factory_id == factory_id)
        .filter(Movement.source.like("factory%"))
        .filter(Movement.destination == "shop")
        .filter(Movement.timestamp >= start)
        .filter(Movement.timestamp < end)
        .scalar()
    )

    return int(total or 0)


def _build_manager_dashboard(factory_id: int):
    """
    Minimal manager dashboard: products-focused, launch-ready.
    NO fabrics, NO shop orders.
    """

    # --- stock values ---
    factory_uzs, factory_usd = product_service.total_stock_value(factory_id=factory_id)
    shop_uzs, shop_usd = product_service.shop_stock_totals(factory_id=factory_id)

    # --- shop low stock ---
    shop_low_stock_count, shop_low_stock_items = _get_shop_low_stock(factory_id=factory_id)

    # --- yesterday transfer total ---
    yesterday_transfer_total = _get_yesterday_transfer_total(factory_id=factory_id)

    # --- production today summary ---
    produced_today_total, produced_today_models, prod_today_rows = _get_production_today_summary(factory_id)

    # --- cash (optional but useful) ---
    cash_total_uzs, cash_total_usd = _calc_cash_totals(factory_id=factory_id)

    return {
        "factory_uzs": factory_uzs,
        "shop_uzs": shop_uzs,
        "total_uzs": (factory_uzs + shop_uzs),

        "cash_total_uzs": cash_total_uzs,
        "cash_total_usd": cash_total_usd,

        "shop_low_stock_count": shop_low_stock_count,
        "shop_low_stock_items": shop_low_stock_items,

        "yesterday_transfer_total": yesterday_transfer_total,

        "produced_today_total": produced_today_total,
        "produced_today_models": produced_today_models,
        "prod_today_rows": prod_today_rows,
    }


@main_bp.route("/")
@login_required
def dashboard():
    # ✅ SAFETY NET: shop users must never see manager dashboard
    role = getattr(current_user, "role", "manager")
    if role == "shop" or getattr(current_user, "is_shop", False):
        return redirect(url_for("shop.dashboard_shop"))

    factory_id = getattr(current_user, "factory_id", None)
    current_date = _get_current_date_for_lang()

    # If for some reason factory_id is missing, still render something safe
    if not factory_id:
        # You can later flash a message here if you want
        return render_template("dashboard.html", current_date=current_date)

    data = _build_manager_dashboard(factory_id=factory_id)
    data["current_date"] = current_date

    # Keep your existing templates logic:
    # - manager uses dashboard_manager.html
    # - others can still fallback to dashboard.html (same data)
    if role == "manager" or getattr(current_user, "is_manager", False):
        return render_template("dashboard_manager.html", **data)

    return render_template("dashboard.html", **data)