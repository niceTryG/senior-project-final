from datetime import datetime, date, timedelta

from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import func

from ..extensions import db
from ..forms import ProfileUpdateForm, ChangePasswordForm, TelegramLinkCodeForm
from ..models import CashRecord, Production, Product, ShopStock, Sale, StockMovement, User, TelegramLinkCode
from ..services.product_service import ProductService
from ..translations import t as translate


main_bp = Blueprint("main", __name__)
product_service = ProductService()


def _resolve_telegram_link_factory_id(user) -> int | None:
    factory_id = getattr(user, "factory_id", None)
    if factory_id:
        return int(factory_id)

    shop = getattr(user, "shop", None)
    if shop and getattr(shop, "factory_id", None):
        return int(shop.factory_id)

    session_factory_id = session.get("factory_id")
    try:
        return int(session_factory_id) if session_factory_id else None
    except (TypeError, ValueError):
        return None


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
    total_uzs = sum(float(r.amount or 0) for r in records if (r.currency or "UZS").upper() == "UZS")
    total_usd = sum(float(r.amount or 0) for r in records if (r.currency or "UZS").upper() == "USD")
    return total_uzs, total_usd


def _get_production_today_summary(factory_id: int):
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

    produced_today_total = int(sum(int(qty or 0) for _, qty in rows))
    produced_today_models = int(len(rows))
    return produced_today_total, produced_today_models, rows


def _get_production_week_total(factory_id: int):
    today = date.today()
    week_start = today - timedelta(days=6)

    total = (
        db.session.query(func.coalesce(func.sum(Production.quantity), 0))
        .join(Product, Product.id == Production.product_id)
        .filter(Product.factory_id == factory_id)
        .filter(Production.date >= week_start)
        .filter(Production.date <= today)
        .scalar()
    )
    return int(total or 0)


def _get_shop_low_stock(factory_id: int, threshold: int = 5, limit: int = 3):
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
    y = date.today() - timedelta(days=1)
    start = datetime(y.year, y.month, y.day, 0, 0, 0)
    end = start + timedelta(days=1)

    total = (
        db.session.query(func.coalesce(func.sum(StockMovement.qty_change), 0))
        .filter(StockMovement.factory_id == factory_id)
        .filter(
            StockMovement.movement_type.in_(("factory_to_shop", "factory_to_shop_for_order"))
        )
        .filter(StockMovement.timestamp >= start)
        .filter(StockMovement.timestamp < end)
        .scalar()
    )

    return int(total or 0)


def _sale_amount_uzs(sale, product) -> float:
    if hasattr(sale, "total_sell") and sale.total_sell is not None:
        try:
            return float(sale.total_sell or 0)
        except Exception:
            return 0.0

    qty = getattr(sale, "quantity", 0) or 0
    price = getattr(sale, "sell_price_per_item", None)
    if price is None:
        price = getattr(product, "sell_price_per_item", 0) or 0

    try:
        return float(qty) * float(price)
    except Exception:
        return 0.0


def _get_sales_dashboard_stats(factory_id: int):
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=6)

    rows = (
        db.session.query(Sale, Product)
        .join(Product, Product.id == Sale.product_id)
        .filter(Product.factory_id == factory_id)
        .all()
    )

    today_sales_uzs = 0.0
    yesterday_sales_uzs = 0.0
    week_sales_uzs = 0.0

    by_product = {}

    for sale, product in rows:
        raw_sale_date = getattr(sale, "date", None)
        if not raw_sale_date:
            continue

        if isinstance(raw_sale_date, datetime):
            s_date = raw_sale_date.date()
        else:
            s_date = raw_sale_date

        amount = _sale_amount_uzs(sale, product)

        if s_date == today:
            today_sales_uzs += amount
        if s_date == yesterday:
            yesterday_sales_uzs += amount
        if week_start <= s_date <= today:
            week_sales_uzs += amount

        pid = product.id
        if pid not in by_product:
            by_product[pid] = {
                "product_id": pid,
                "name": product.name,
                "qty": 0,
                "amount_uzs": 0.0,
            }

        by_product[pid]["qty"] += int(getattr(sale, "quantity", 0) or 0)
        by_product[pid]["amount_uzs"] += amount

    top_selling_models = sorted(
        by_product.values(),
        key=lambda x: (x["qty"], x["amount_uzs"]),
        reverse=True,
    )[:5]

    return {
        "today_sales_uzs": today_sales_uzs,
        "yesterday_sales_uzs": yesterday_sales_uzs,
        "week_sales_uzs": week_sales_uzs,
        "top_selling_models": top_selling_models,
    }


def _build_manager_dashboard(factory_id: int):
    factory_uzs, factory_usd = product_service.total_stock_value(factory_id=factory_id)
    shop_uzs, shop_usd = product_service.shop_stock_totals(factory_id=factory_id)

    shop_low_stock_count, shop_low_stock_items = _get_shop_low_stock(factory_id=factory_id)
    yesterday_transfer_total = _get_yesterday_transfer_total(factory_id=factory_id)

    produced_today_total, produced_today_models, prod_today_rows = _get_production_today_summary(factory_id)
    produced_week_total = _get_production_week_total(factory_id)

    cash_total_uzs, cash_total_usd = _calc_cash_totals(factory_id=factory_id)
    sales_stats = _get_sales_dashboard_stats(factory_id=factory_id)

    return {
        "factory_uzs": factory_uzs,
        "shop_uzs": shop_uzs,
        "total_uzs": factory_uzs + shop_uzs,

        "factory_usd": factory_usd,
        "shop_usd": shop_usd,
        "total_usd": factory_usd + shop_usd,

        "cash_total_uzs": cash_total_uzs,
        "cash_total_usd": cash_total_usd,

        "shop_low_stock_count": shop_low_stock_count,
        "shop_low_stock_items": shop_low_stock_items,

        "yesterday_transfer_total": yesterday_transfer_total,

        "produced_today_total": produced_today_total,
        "produced_today_models": produced_today_models,
        "produced_week_total": produced_week_total,
        "prod_today_rows": prod_today_rows,

        "today_sales_uzs": sales_stats["today_sales_uzs"],
        "yesterday_sales_uzs": sales_stats["yesterday_sales_uzs"],
        "week_sales_uzs": sales_stats["week_sales_uzs"],
        "top_selling_models": sales_stats["top_selling_models"],
    }


@main_bp.route("/dashboard")
@login_required
def dashboard():
    role = getattr(current_user, "role", "manager")

    if role == "shop" or getattr(current_user, "is_shop", False):
        return redirect(url_for("shop.dashboard_shop"))

    factory_id = getattr(current_user, "factory_id", None)
    current_date = _get_current_date_for_lang()

    if not factory_id:
        return render_template("dashboard.html", current_date=current_date)

    data = _build_manager_dashboard(factory_id=factory_id)
    data["current_date"] = current_date

    manager_like_roles = {"manager", "admin", "accountant", "viewer"}

    if role in manager_like_roles or getattr(current_user, "is_manager", False):
        return render_template("dashboard_manager.html", **data)

    return render_template("dashboard.html", **data)


@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    profile_form = ProfileUpdateForm(prefix="profile")
    password_form = ChangePasswordForm(prefix="password")
    telegram_form = TelegramLinkCodeForm(prefix="telegram")

    if request.method == "GET":
        profile_form.username.data = current_user.username

    if profile_form.submit_profile.data and profile_form.validate_on_submit():
        new_username = (profile_form.username.data or "").strip()

        existing_user = User.query.filter(
            func.lower(User.username) == func.lower(new_username),
            User.id != current_user.id
        ).first()

        if existing_user:
            flash("This username is already taken.", "danger")
        else:
            current_user.username = new_username
            db.session.commit()
            flash("Profile updated successfully.", "success")
            return redirect(url_for("main.profile"))

    if password_form.submit_password.data and password_form.validate_on_submit():
        current_password = password_form.current_password.data or ""
        new_password = password_form.new_password.data or ""

        if not current_user.check_password(current_password):
            flash("Current password is incorrect.", "danger")
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash("Password updated successfully.", "success")
            return redirect(url_for("main.profile"))

    if telegram_form.submit_telegram_code.data and telegram_form.validate_on_submit():
        factory_id = _resolve_telegram_link_factory_id(current_user)

        if not factory_id:
            flash(translate("profile_telegram_code_missing_factory"), "danger")
        else:
            (
                TelegramLinkCode.query
                .filter(
                    TelegramLinkCode.user_id == current_user.id,
                    TelegramLinkCode.used_at.is_(None),
                )
                .delete(synchronize_session=False)
            )

            link_code = TelegramLinkCode.generate(
                user_id=current_user.id,
                factory_id=factory_id,
                minutes=10,
            )
            db.session.add(link_code)
            db.session.commit()

            flash(translate("profile_telegram_code_generated"), "success")
            return redirect(url_for("main.profile"))

    active_telegram_link = None
    if getattr(current_user, "telegram_links", None):
        active_telegram_link = sorted(
            current_user.telegram_links,
            key=lambda x: getattr(x, "created_at", None) or datetime.min,
            reverse=True,
        )[0]

    active_telegram_code = (
        TelegramLinkCode.query
        .filter(
            TelegramLinkCode.user_id == current_user.id,
            TelegramLinkCode.used_at.is_(None),
            TelegramLinkCode.expires_at > datetime.utcnow(),
        )
        .order_by(TelegramLinkCode.created_at.desc())
        .first()
    )

    return render_template(
        "profile/index.html",
        profile_form=profile_form,
        password_form=password_form,
        telegram_form=telegram_form,
        active_telegram_link=active_telegram_link,
        active_telegram_code=active_telegram_code,
    )
