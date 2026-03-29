from datetime import datetime, timedelta, date
import io

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    session,
    send_file,
    abort,
)
from flask_login import login_required, current_user
from sqlalchemy import or_

from ..extensions import db
from ..auth_utils import roles_required
from ..models import (
    Factory,
    Product,
    Production,
    Shop,
    ShopStock,
    ShopFactoryLink,
    ShopOrder,
    ShopOrderItem,
    StockMovement,
    Sale,
)
from ..services.shop_service import ShopService
from app.telegram_notify import send_telegram_message


shop_bp = Blueprint("shop", __name__, url_prefix="/shop")
shop_service = ShopService()


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


def _is_shared_shop_user() -> bool:
    return bool(
        current_user.is_shop and not (current_user.is_manager or current_user.is_admin)
    )


def _scope_factory_id():
    if _is_shared_shop_user():
        return None
    return current_user.factory_id


def _accessible_shop_ids() -> list[int]:
    """
    Shop-only user:
      - only their assigned shop_id

    Manager/admin:
      - all shops linked to their current factory_id
    """
    if _is_shared_shop_user():
        return [current_user.shop_id] if current_user.shop_id else []

    if not current_user.factory_id:
        return []

    rows = (
        ShopFactoryLink.query.filter_by(factory_id=current_user.factory_id)
        .with_entities(ShopFactoryLink.shop_id)
        .all()
    )
    return [shop_id for (shop_id,) in rows]


def _require_shop_scope_or_redirect():
    """
    Returns:
      - int shop_id for shop-only users
      - list[int] shop_ids for manager/admin users
      - None if access is not possible
    """
    if _is_shared_shop_user():
        if not current_user.shop_id:
            flash("Пользователь не привязан к магазину.", "danger")
            return None
        return current_user.shop_id

    shop_ids = _accessible_shop_ids()
    if not shop_ids:
        flash("Для текущей фабрики нет привязанных магазинов.", "danger")
        return None

    return shop_ids


def _sum_shop_stock_value_uzs(factory_id=None) -> float:
    rows = db.session.query(ShopStock.quantity, Product.sell_price_per_item).join(
        Product, Product.id == ShopStock.product_id
    )

    if factory_id is not None:
        rows = rows.filter(ShopStock.source_factory_id == factory_id)

    if _is_shared_shop_user() and current_user.shop_id:
        rows = rows.filter(ShopStock.shop_id == current_user.shop_id)

    rows = rows.all()

    total = 0.0
    for qty, price in rows:
        total += float(qty or 0) * float(price or 0)
    return total


def _sum_factory_stock_value_uzs(factory_id=None) -> float:
    rows = db.session.query(Product.quantity, Product.sell_price_per_item)

    if factory_id is not None:
        rows = rows.filter(Product.factory_id == factory_id)
    else:
        if _is_shared_shop_user():
            return 0.0

    rows = rows.all()

    total = 0.0
    for qty, price in rows:
        total += float(qty or 0) * float(price or 0)
    return total


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


def _visible_shop_stock_rows_query(factory_id=None):
    """
    Returns a query of visible shop stock rows as:
      (ShopStock, Product, Factory)

    Shared shop user:
      - only their assigned shop

    Manager/admin:
      - all accessible shops linked to current factory
      - if factory_id is provided, restrict to that factory's stock rows
    """
    q = (
        db.session.query(ShopStock, Product, Factory)
        .join(Product, Product.id == ShopStock.product_id)
        .join(Factory, Factory.id == ShopStock.source_factory_id)
    )

    if _is_shared_shop_user():
        if not current_user.shop_id:
            return q.filter(ShopStock.id == -1)
        q = q.filter(ShopStock.shop_id == current_user.shop_id)
    else:
        shop_ids = _accessible_shop_ids()
        if not shop_ids:
            return q.filter(ShopStock.id == -1)

        q = q.filter(ShopStock.shop_id.in_(shop_ids))

        if factory_id is not None:
            q = q.filter(ShopStock.source_factory_id == factory_id)

    return q


def _get_shop_sales_dashboard_stats(factory_id=None):
    """
    Sales totals for shop dashboard.

    Notes:
    - If Sale has factory_id, use it directly.
    - Otherwise fallback to Product.factory_id.
    - If Sale has shop_id and current user is a shared shop user, scope by shop_id too.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=6)
    month_start = today.replace(day=1)

    q = db.session.query(Sale, Product).join(Product, Product.id == Sale.product_id)

    if factory_id is not None:
        if hasattr(Sale, "factory_id"):
            q = q.filter(Sale.factory_id == factory_id)
        else:
            q = q.filter(Product.factory_id == factory_id)
    elif _is_shared_shop_user():
        if hasattr(Sale, "shop_id") and current_user.shop_id:
            q = q.filter(Sale.shop_id == current_user.shop_id)

    rows = q.all()

    today_sales_uzs = 0.0
    yesterday_sales_uzs = 0.0
    week_sales_uzs = 0.0
    month_sales_uzs = 0.0

    for sale, product in rows:
        raw_sale_date = getattr(sale, "date", None)

        if not raw_sale_date and hasattr(sale, "created_at"):
            raw_sale_date = getattr(sale, "created_at", None)

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
        if month_start <= s_date <= today:
            month_sales_uzs += amount

    return {
        "today_sales_uzs": today_sales_uzs,
        "yesterday_sales_uzs": yesterday_sales_uzs,
        "week_sales_uzs": week_sales_uzs,
        "month_sales_uzs": month_sales_uzs,
    }


def _build_shop_dashboard_stats(factory_id=None):
    """
    Rich shop dashboard stats, including:
    - shop stock totals
    - low stock count
    - total SKUs / qty
    - per-factory stock breakdown
    - today/yesterday/week/month sales
    """
    rows = _visible_shop_stock_rows_query(factory_id=factory_id).all()

    total_shop_value_uzs = 0.0
    total_shop_qty = 0
    low_stock_count = 0

    sku_keys = set()
    by_factory = {}

    for stock, product, factory in rows:
        qty = int(stock.quantity or 0)
        price = float(product.sell_price_per_item or 0)
        value = qty * price

        total_shop_qty += qty
        total_shop_value_uzs += value

        if qty < 5:
            low_stock_count += 1

        sku_keys.add((stock.product_id, stock.source_factory_id))

        fid = factory.id
        if fid not in by_factory:
            by_factory[fid] = {
                "factory_id": fid,
                "factory_name": factory.name,
                "sku_set": set(),
                "total_qty": 0,
                "total_value_uzs": 0.0,
                "low_stock_count": 0,
            }

        by_factory[fid]["sku_set"].add(stock.product_id)
        by_factory[fid]["total_qty"] += qty
        by_factory[fid]["total_value_uzs"] += value

        if qty < 5:
            by_factory[fid]["low_stock_count"] += 1

    factory_breakdown = []
    for item in by_factory.values():
        factory_breakdown.append(
            {
                "factory_id": item["factory_id"],
                "factory_name": item["factory_name"],
                "sku_count": len(item["sku_set"]),
                "total_qty": item["total_qty"],
                "total_value_uzs": item["total_value_uzs"],
                "low_stock_count": item["low_stock_count"],
            }
        )

    factory_breakdown.sort(
        key=lambda x: (x["total_value_uzs"], x["total_qty"]),
        reverse=True,
    )

    sales_stats = _get_shop_sales_dashboard_stats(factory_id=factory_id)

    return {
        "shop_total_value_uzs": total_shop_value_uzs,
        "shop_total_skus": len(sku_keys),
        "shop_total_qty": total_shop_qty,
        "low_stock_count": low_stock_count,
        "factory_breakdown": factory_breakdown,
        "today_sales_uzs": sales_stats["today_sales_uzs"],
        "yesterday_sales_uzs": sales_stats["yesterday_sales_uzs"],
        "week_sales_uzs": sales_stats["week_sales_uzs"],
        "month_sales_uzs": sales_stats["month_sales_uzs"],
    }


def _shop_orders_base_query(factory_id=None):
    q = ShopOrder.query
    if factory_id is not None:
        q = q.filter(ShopOrder.factory_id == factory_id)
    return q


def _shared_shop_product_or_404(product_id: int):
    if _is_shared_shop_user():
        product = (
            Product.query.join(ShopStock, ShopStock.product_id == Product.id)
            .filter(Product.id == product_id, ShopStock.shop_id == current_user.shop_id)
            .first_or_404()
        )
        return product

    return Product.query.filter_by(
        id=product_id,
        factory_id=current_user.factory_id,
    ).first_or_404()


@shop_bp.route("/dashboard", methods=["GET"])
@login_required
@roles_required("shop", "manager", "admin")
def dashboard_shop():
    factory_id = _scope_factory_id()
    current_date = _get_current_date_for_lang()

    try:
        dashboard_stats = _build_shop_dashboard_stats(factory_id=factory_id)
    except Exception:
        dashboard_stats = {
            "shop_total_value_uzs": 0.0,
            "shop_total_skus": 0,
            "shop_total_qty": 0,
            "low_stock_count": 0,
            "factory_breakdown": [],
            "today_sales_uzs": 0.0,
            "yesterday_sales_uzs": 0.0,
            "week_sales_uzs": 0.0,
            "month_sales_uzs": 0.0,
        }

    try:
        shop_uzs = float(dashboard_stats.get("shop_total_value_uzs", 0.0) or 0.0)
    except Exception:
        shop_uzs = 0.0

    try:
        factory_uzs = _sum_factory_stock_value_uzs(factory_id=factory_id)
    except Exception:
        factory_uzs = 0.0

    total_uzs = float(factory_uzs or 0) + float(shop_uzs or 0)

    orders_q = _shop_orders_base_query(factory_id=factory_id)

    if _is_shared_shop_user():
        orders_q = orders_q.filter(ShopOrder.created_by_id == current_user.id)

    shop_orders_pending = orders_q.filter(ShopOrder.status == "pending").count()
    shop_orders_ready = orders_q.filter(ShopOrder.status == "ready").count()
    shop_orders_completed = orders_q.filter(ShopOrder.status == "completed").count()

    counts = {
        "pending": shop_orders_pending,
        "ready": shop_orders_ready,
        "completed": shop_orders_completed,
    }
    try:
        daily_sales_labels, daily_sales_values = _get_daily_sales_chart_data(
            factory_id=factory_id,
            days=7,
        )
    except Exception:
        daily_sales_labels, daily_sales_values = [], []

    try:
        factory_sales_labels, factory_sales_values = _get_factory_sales_chart_data(
            factory_id=factory_id
        )
    except Exception:
        factory_sales_labels, factory_sales_values = [], []

    dashboard_stats["orders_pending"] = shop_orders_pending
    dashboard_stats["orders_ready"] = shop_orders_ready
    dashboard_stats["orders_completed"] = shop_orders_completed
    

    return render_template(
        "shop/dashboard_shop.html",
        stats=dashboard_stats,
        shop_uzs=shop_uzs,
        factory_uzs=factory_uzs,
        total_uzs=total_uzs,
        shop_orders_pending=shop_orders_pending,
        shop_orders_ready=shop_orders_ready,
        current_date=current_date,
        counts=counts,
        daily_sales_labels=daily_sales_labels,
        daily_sales_values=daily_sales_values,
        factory_sales_labels=factory_sales_labels,
        factory_sales_values=factory_sales_values,
        shop_factory_breakdown=dashboard_stats.get("factory_breakdown", []),
    )


@shop_bp.route("/", methods=["GET"])
@login_required
def list_shop():
    q_raw = request.args.get("q") or ""
    q = q_raw.strip()
    sort = request.args.get("sort", "name")
    stock_filter = (request.args.get("stock_filter") or "").strip().lower()
    factory_filter = request.args.get("factory_id", type=int)

    shop_scope = _require_shop_scope_or_redirect()
    if shop_scope is None:
        return redirect(url_for("main.dashboard"))

    base_query = (
        db.session.query(ShopStock)
        .join(Product, Product.id == ShopStock.product_id)
        .join(Factory, Factory.id == ShopStock.source_factory_id)
    )

    if _is_shared_shop_user():
        base_query = base_query.filter(ShopStock.shop_id == shop_scope)
    else:
        base_query = base_query.filter(ShopStock.shop_id.in_(shop_scope))

        if current_user.factory_id:
            base_query = base_query.filter(
                ShopStock.source_factory_id == current_user.factory_id
            )

    all_visible_items = base_query.order_by(
        Factory.name.asc(), Product.name.asc()
    ).all()

    overall_total_qty = 0
    overall_total_value_uzs = 0
    overall_low_stock_count = 0
    overall_out_of_stock_count = 0
    overall_available_count = 0

    factory_summary_map = {}

    for row in all_visible_items:
        qty = row.quantity or 0
        price = row.product.sell_price_per_item or 0
        row_value = qty * price

        overall_total_qty += qty
        overall_total_value_uzs += row_value

        if qty <= 0:
            overall_out_of_stock_count += 1
        else:
            overall_available_count += 1
            if qty < 5:
                overall_low_stock_count += 1

        fid = row.source_factory_id or 0
        if fid not in factory_summary_map:
            factory_summary_map[fid] = {
                "factory_id": fid,
                "factory_name": row.source_factory.name if row.source_factory else "—",
                "items_count": 0,
                "total_qty": 0,
                "total_value_uzs": 0,
                "low_stock_count": 0,
                "out_of_stock_count": 0,
            }

        factory_summary_map[fid]["items_count"] += 1
        factory_summary_map[fid]["total_qty"] += qty
        factory_summary_map[fid]["total_value_uzs"] += row_value

        if qty <= 0:
            factory_summary_map[fid]["out_of_stock_count"] += 1
        elif qty < 5:
            factory_summary_map[fid]["low_stock_count"] += 1

    factory_summary = sorted(
        factory_summary_map.values(),
        key=lambda x: (x["total_value_uzs"], x["total_qty"]),
        reverse=True,
    )

    for item in factory_summary:
        if overall_total_value_uzs > 0:
            item["share_pct"] = round(
                (item["total_value_uzs"] / overall_total_value_uzs) * 100
            )
        else:
            item["share_pct"] = 0

    selected_factory = None
    if factory_filter:
        selected_factory = next(
            (f for f in factory_summary if f["factory_id"] == factory_filter),
            None,
        )

    items_query = base_query

    if factory_filter:
        items_query = items_query.filter(ShopStock.source_factory_id == factory_filter)

    if q:
        like = f"%{q}%"
        items_query = items_query.filter(
            or_(
                Product.name.ilike(like),
                Product.category.ilike(like),
                Factory.name.ilike(like),
            )
        )

    if stock_filter == "low":
        items_query = items_query.filter(ShopStock.quantity > 0, ShopStock.quantity < 5)
    elif stock_filter == "out":
        items_query = items_query.filter(ShopStock.quantity <= 0)
    elif stock_filter == "available":
        items_query = items_query.filter(ShopStock.quantity > 0)

    if sort == "qty":
        items_query = items_query.order_by(
            ShopStock.quantity.desc(), Product.name.asc()
        )
    elif sort == "factory":
        items_query = items_query.order_by(Factory.name.asc(), Product.name.asc())
    else:
        items_query = items_query.order_by(Product.name.asc(), Factory.name.asc())

    items = items_query.all()

    total_qty = sum((row.quantity or 0) for row in items)
    total_value_uzs = 0
    low_stock_count = 0
    out_of_stock_count = 0
    available_count = 0

    for row in items:
        qty = row.quantity or 0
        price = row.product.sell_price_per_item or 0
        total_value_uzs += qty * price

        if qty <= 0:
            out_of_stock_count += 1
        else:
            available_count += 1
            if qty < 5:
                low_stock_count += 1

    accessible_factories = sorted(
        {
            row.source_factory
            for row in all_visible_items
            if row.source_factory is not None
        },
        key=lambda f: f.name.lower(),
    )

    common_context = dict(
        items=items,
        total_qty=total_qty,
        total_value_uzs=total_value_uzs,
        q=q,
        sort=sort,
        stock_filter=stock_filter,
        factory_filter=factory_filter,
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count,
        available_count=available_count,
        factory_summary=factory_summary,
        accessible_factories=accessible_factories,
        selected_factory=selected_factory,
        show_factory_overview=(factory_filter is None),
        show_factory_products=(factory_filter is not None),
        overall_total_qty=overall_total_qty,
        overall_total_value_uzs=overall_total_value_uzs,
        overall_low_stock_count=overall_low_stock_count,
        overall_out_of_stock_count=overall_out_of_stock_count,
        overall_available_count=overall_available_count,
    )

    if _is_shared_shop_user():
        return render_template("shop/list_staff.html", **common_context)

    return render_template("shop/list.html", **common_context)


@shop_bp.route("/transfer", methods=["GET", "POST"])
@login_required
@roles_required("admin", "manager")
def transfer_to_shop():
    factory_id = current_user.factory_id

    if request.method == "POST":
        try:
            product_id = int(request.form.get("product_id") or 0)
            quantity = int(request.form.get("quantity") or 0)
            shop_id = int(request.form.get("shop_id") or 0)
        except ValueError:
            flash("Ошибка в данных формы.", "danger")
            return redirect(url_for("shop.transfer_to_shop"))

        price_raw = (request.form.get("sell_price_per_item") or "").strip()
        sell_price_per_item = None

        if price_raw:
            try:
                sell_price_per_item = float(price_raw.replace(",", "."))
            except ValueError:
                flash("Неверная цена продажи.", "warning")
                return redirect(url_for("shop.transfer_to_shop"))

        product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
        if not product:
            flash("Товар не найден.", "danger")
            return redirect(url_for("shop.transfer_to_shop"))

        link_exists = ShopFactoryLink.query.filter_by(
            shop_id=shop_id,
            factory_id=factory_id,
        ).first()

        if not link_exists:
            flash("Этот магазин не привязан к текущей фабрике.", "danger")
            return redirect(url_for("shop.transfer_to_shop"))

        try:
            result = shop_service.transfer_factory_to_shop(
                factory_id=factory_id,
                shop_id=shop_id,
                product_id=product.id,
                quantity=quantity,
                sell_price_per_item=sell_price_per_item,
                created_by=current_user,
            )
            fulfilled_order_ids = result["fulfilled_order_ids"]
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("shop.transfer_to_shop"))
        except Exception as e:
            db.session.rollback()
            flash(f"Ошибка передачи: {str(e)}", "danger")
            return redirect(url_for("shop.transfer_to_shop"))

        try:
            msg = (
                "🚚 <b>Передача в магазин</b>\n"
                f"Модель: <b>{product.name}</b>\n"
                f"Количество: <b>{quantity}</b> шт.\n"
                f"Фабрика: <b>{product.factory_id}</b>"
            )
            send_telegram_message(
                msg,
                factory_id=product.factory_id,
                include_manager_chats=False,
            )
        except Exception:
            pass

        if fulfilled_order_ids:
            flash(
                "Товар успешно передан в магазин. "
                f"Обновлены заказы: {', '.join('#' + str(x) for x in sorted(fulfilled_order_ids))}.",
                "success",
            )
        else:
            flash("Товар успешно передан в магазин.", "success")

        return redirect(url_for("shop.list_shop"))

    mode = (request.args.get("mode") or "today").strip().lower()

    if mode == "all":
        products = (
            Product.query.filter_by(factory_id=factory_id)
            .order_by(Product.name.asc())
            .all()
        )
    else:
        produced_ids = (
            db.session.query(Production.product_id)
            .join(Product, Product.id == Production.product_id)
            .filter(Product.factory_id == factory_id)
            .filter(Production.date == date.today())
            .group_by(Production.product_id)
            .all()
        )
        produced_ids = [pid for (pid,) in produced_ids]

        if produced_ids:
            products = (
                Product.query.filter(
                    Product.factory_id == factory_id,
                    Product.id.in_(produced_ids),
                )
                .order_by(Product.name.asc())
                .all()
            )
        else:
            products = (
                Product.query.filter(
                    Product.factory_id == factory_id,
                    Product.quantity > 0,
                )
                .order_by(Product.name.asc())
                .all()
            )

    linked_shop_ids = [
        row.shop_id
        for row in ShopFactoryLink.query.filter_by(factory_id=factory_id).all()
    ]

    shops = (
        Shop.query.filter(Shop.id.in_(linked_shop_ids)).order_by(Shop.name.asc()).all()
        if linked_shop_ids
        else []
    )

    return render_template(
        "shop/transfer.html",
        products=products,
        mode=mode,
        shops=shops,
    )


@shop_bp.route("/export", methods=["GET"])
@login_required
def export_shop():
    if _is_shared_shop_user():
        if not current_user.shop_id:
            flash("Пользователь не привязан к магазину.", "danger")
            return redirect(url_for("main.dashboard"))
        shop_id = current_user.shop_id
    else:
        accessible_shop_ids = _accessible_shop_ids()
        if not accessible_shop_ids:
            flash("Для текущей фабрики нет привязанных магазинов.", "danger")
            return redirect(url_for("main.dashboard"))

        requested_shop_id = request.args.get("shop_id", type=int)

        if requested_shop_id:
            if requested_shop_id not in accessible_shop_ids:
                flash("Нет доступа к выбранному магазину.", "danger")
                return redirect(url_for("main.dashboard"))
            shop_id = requested_shop_id
        elif len(accessible_shop_ids) == 1:
            shop_id = accessible_shop_ids[0]
        else:
            flash("Укажите shop_id для экспорта магазина.", "warning")
            return redirect(url_for("shop.list_shop"))

    xlsx_bytes = shop_service.export_full_report_xlsx(
        shop_id=shop_id,
        q=request.args.get("q"),
        sort=request.args.get("sort", "name"),
    )

    if isinstance(xlsx_bytes, str):
        xlsx_bytes = xlsx_bytes.encode("utf-8")

    buf = io.BytesIO(xlsx_bytes)
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name="mini_moda_shop_report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        max_age=0,
    )


@shop_bp.route("/orders", methods=["GET"])
@login_required
@roles_required("shop", "manager", "admin")
def list_shop_orders():
    factory_id = _scope_factory_id()
    status = (request.args.get("status") or "").strip().lower()

    query = _shop_orders_base_query(factory_id=factory_id)

    if _is_shared_shop_user():
        query = query.filter(ShopOrder.created_by_id == current_user.id)

    if status in ("pending", "ready", "completed", "cancelled"):
        query = query.filter(ShopOrder.status == status)

    orders = query.order_by(ShopOrder.created_at.desc()).all()

    base_query = _shop_orders_base_query(factory_id=factory_id)
    if _is_shared_shop_user():
        base_query = base_query.filter(ShopOrder.created_by_id == current_user.id)

    counts = {
        "pending": base_query.filter(ShopOrder.status == "pending").count(),
        "ready": base_query.filter(ShopOrder.status == "ready").count(),
        "completed": base_query.filter(ShopOrder.status == "completed").count(),
        "cancelled": base_query.filter(ShopOrder.status == "cancelled").count(),
    }

    return render_template(
        "shop/orders_list.html",
        orders=orders,
        status=status,
        counts=counts,
    )


@shop_bp.route("/orders/<int:order_id>/status", methods=["POST"])
@login_required
@roles_required("shop", "manager", "admin")
def update_shop_order_status(order_id: int):
    factory_id = _scope_factory_id()

    order_q = ShopOrder.query.filter(ShopOrder.id == order_id)
    if factory_id is not None:
        order_q = order_q.filter(ShopOrder.factory_id == factory_id)

    order = order_q.first_or_404()
    new_status = (request.form.get("status") or "").strip().lower()

    if new_status not in ("pending", "ready", "completed", "cancelled"):
        flash("Неверный статус заказа.", "warning")
        return redirect(url_for("shop.list_shop_orders"))

    if _is_shared_shop_user():
        if order.created_by_id != current_user.id:
            flash("Вы можете менять статус только своих заказов.", "danger")
            return redirect(url_for("shop.list_shop_orders"))

    order.status = new_status

    if new_status == "ready" and order.ready_at is None:
        order.ready_at = datetime.utcnow()
    if new_status == "completed" and order.completed_at is None:
        order.completed_at = datetime.utcnow()

    db.session.commit()
    flash(f"Статус заказа #{order.id} обновлён на: {new_status}.", "success")
    return redirect(url_for("shop.list_shop_orders"))


@shop_bp.route("/factory-pending", methods=["GET"])
@login_required
@roles_required("admin", "manager")
def factory_pending_orders():
    orders = (
        ShopOrder.query.filter_by(factory_id=current_user.factory_id, status="pending")
        .order_by(ShopOrder.created_at.asc())
        .all()
    )
    return render_template("shop/orders_for_factory.html", orders=orders)


@shop_bp.route("/orders/item/<int:item_id>/ship", methods=["POST"])
@login_required
@roles_required("manager", "admin")
def ship_order_item(item_id: int):
    factory_id = current_user.factory_id

    try:
        ship_qty = int(request.form.get("ship_qty") or 0)
    except (TypeError, ValueError):
        ship_qty = 0

    try:
        result = shop_service.ship_order_item_to_shop(
            item_id=item_id,
            ship_qty=ship_qty,
            factory_id=factory_id,
            created_by=current_user,
        )
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("shop.factory_pending_orders"))

    order = result["order"]
    ship_qty = result["ship_qty"]

    flash(f"Отправлено в магазин {ship_qty} шт. для заказа #{order.id}.", "success")
    return redirect(url_for("shop.factory_pending_orders"))


@shop_bp.route("/history", methods=["GET"])
@login_required
def movement_history():
    factory_id = _scope_factory_id()

    product_id = request.args.get("product_id", type=int)
    order_id = request.args.get("order_id", type=int)
    movement_type = (request.args.get("type") or "").strip()
    date_from_str = (request.args.get("from") or "").strip()
    date_to_str = (request.args.get("to") or "").strip()

    date_from = None
    date_to = None

    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d")
        except ValueError:
            date_from = None

    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            date_to = None

    query = StockMovement.query.join(Product)

    if factory_id is not None:
        query = query.filter(Product.factory_id == factory_id)

    if product_id:
        query = query.filter(StockMovement.product_id == product_id)

    if order_id:
        query = query.filter(StockMovement.order_id == order_id)

    if movement_type in (
        "factory_to_shop",
        "factory_to_shop_for_order",
        "shop_sale",
        "adjustment",
    ):
        query = query.filter(StockMovement.movement_type == movement_type)

    if date_from:
        query = query.filter(StockMovement.timestamp >= date_from)

    if date_to:
        query = query.filter(StockMovement.timestamp < date_to)

    movements = query.order_by(StockMovement.timestamp.desc()).all()

    products_q = Product.query
    if factory_id is not None:
        products_q = products_q.filter_by(factory_id=factory_id)

    products = products_q.order_by(Product.name.asc()).all()

    return render_template(
        "history/movements.html",
        movements=movements,
        products=products,
        filter_product_id=product_id,
        filter_order_id=order_id or "",
        filter_type=movement_type,
        filter_from=date_from_str,
        filter_to=date_to_str,
    )


@shop_bp.route("/api/stock-low")
@login_required
def shop_stock_low():
    q = ShopStock.query.join(Product)

    factory_id = _scope_factory_id()
    if factory_id is not None:
        q = q.filter(ShopStock.source_factory_id == factory_id)

    if current_user.shop_id:
        q = q.filter(ShopStock.shop_id == current_user.shop_id)

    low = q.filter(ShopStock.quantity < 5).all()

    return jsonify(
        {
            "low_stock": [
                {"id": row.product.id, "name": row.product.name, "qty": row.quantity}
                for row in low
            ]
        }
    )


@shop_bp.route("/history/order/<int:order_id>", methods=["GET"])
@login_required
@roles_required("shop", "manager", "admin")
def history_by_order(order_id: int):
    factory_id = _scope_factory_id()

    order_q = ShopOrder.query.filter(ShopOrder.id == order_id)
    if factory_id is not None:
        order_q = order_q.filter(ShopOrder.factory_id == factory_id)

    order = order_q.first_or_404()

    movements_q = StockMovement.query.filter(StockMovement.order_id == order_id)

    if factory_id is not None:
        movements_q = movements_q.filter(StockMovement.factory_id == factory_id)

    movements = movements_q.order_by(StockMovement.timestamp.desc()).all()

    return render_template(
        "history/order_movements.html",
        order=order,
        movements=movements,
    )


@shop_bp.route("/sell/<int:shop_stock_id>", methods=["GET", "POST"])
@login_required
@roles_required("shop", "manager", "admin")
def sell_product(shop_stock_id: int):
    stock = ShopStock.query.get_or_404(shop_stock_id)

    if _is_shared_shop_user():
        if not current_user.shop_id or stock.shop_id != current_user.shop_id:
            abort(403)
    else:
        accessible_shop_ids = _accessible_shop_ids()
        if stock.shop_id not in accessible_shop_ids:
            abort(403)

        if (
            current_user.factory_id
            and stock.source_factory_id != current_user.factory_id
        ):
            abort(403)

    product = stock.product
    available = stock.quantity or 0
    effective_factory_id = stock.source_factory_id

    if request.method == "POST":
        try:
            requested_qty = int(request.form.get("quantity") or 0)
        except ValueError:
            flash("Неверное количество.", "danger")
            return redirect(url_for("shop.sell_product", shop_stock_id=stock.id))

        if requested_qty <= 0:
            flash("Количество должно быть больше нуля.", "warning")
            return redirect(url_for("shop.sell_product", shop_stock_id=stock.id))

        customer_name = (request.form.get("customer_name") or "").strip() or None
        customer_phone = (request.form.get("customer_phone") or "").strip() or None
        note = (request.form.get("note") or "").strip() or None
        allow_partial_sale = bool(request.form.get("allow_partial_sale"))

        try:
            result = shop_service.sell_from_shop_or_create_order(
                factory_id=effective_factory_id,
                product_id=product.id,
                requested_qty=requested_qty,
                customer_name=customer_name,
                customer_phone=customer_phone,
                note=note,
                allow_partial_sale=allow_partial_sale,
                created_by=current_user,
                shop_stock_id=stock.id,
            )
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("shop.sell_product", shop_stock_id=stock.id))

        sale = result["sale"]
        order = result["order"]
        missing = result["missing"]
        sold_now = result["sold_now"]

        if sale:
            qty = sale.quantity or 0
            currency = getattr(sale, "currency", None) or getattr(
                product, "currency", "UZS"
            )

            if getattr(sale, "total_sell", None) is not None:
                total_sell = sale.total_sell
            else:
                price = getattr(sale, "sell_price_per_item", None)
                if price is None:
                    price = getattr(product, "sell_price_per_item", 0) or 0
                total_sell = qty * price

            try:
                msg = (
                    "💸 <b>Новая продажа (магазин)</b>\n"
                    f"Модель: <b>{product.name}</b>\n"
                    f"Категория: {product.category or '-'}\n"
                    f"Кол-во: <b>{qty}</b> шт.\n"
                    f"Сумма: <b>{total_sell:.2f} {currency}</b>\n"
                    f"Клиент: {customer_name or '-'}\n"
                    f"Фабрика-источник: <b>{stock.source_factory.name if stock.source_factory else '-'}</b>"
                )
                send_telegram_message(
                    msg,
                    factory_id=effective_factory_id,
                    include_manager_chats=False,
                )
            except Exception:
                pass

        if order:
            try:
                msg = (
                    "🧾 <b>Новый заказ из магазина</b>\n"
                    f"Модель: <b>{product.name}</b>\n"
                    f"Нужно произвести: <b>{missing}</b> шт.\n"
                    f"Номер заказа: <b>{order.id}</b>"
                )
                send_telegram_message(
                    msg,
                    factory_id=effective_factory_id,
                    include_manager_chats=False,
                )
            except Exception:
                pass

        if sale and order:
            flash(
                f"Продано сейчас {sold_now} шт. Остаток {missing} шт. оформлен как заказ №{order.id}.",
                "success",
            )
        elif sale:
            flash(f"Продано {sold_now} шт. из магазина.", "success")
        elif order:
            flash(
                f"Товара не хватило, создан заказ №{order.id} на {missing} шт.",
                "warning",
            )

        return redirect(url_for("shop.list_shop"))

    return render_template(
        "shop/sell.html",
        product=product,
        stock_qty=available,
        shop_stock=stock,
    )


@shop_bp.route("/orders/<int:order_id>/complete", methods=["POST"])
@login_required
@roles_required("shop", "manager", "admin")
def complete_shop_order(order_id: int):
    factory_id = _scope_factory_id()

    order_q = ShopOrder.query.filter(ShopOrder.id == order_id)
    if factory_id is not None:
        order_q = order_q.filter(ShopOrder.factory_id == factory_id)

    order = order_q.first_or_404()

    if _is_shared_shop_user():
        if order.created_by_id != current_user.id:
            flash("Вы можете завершать только свои заказы.", "danger")
            return redirect(url_for("shop.list_shop_orders"))

    if order.status != "ready":
        flash("Завершить можно только заказ со статусом 'Готов к выдаче'.", "warning")
        return redirect(url_for("shop.list_shop_orders"))

    order.status = "completed"
    if order.completed_at is None:
        order.completed_at = datetime.utcnow()

    db.session.commit()

    try:
        items_text = []
        for item in order.items[:10]:
            items_text.append(f"• {item.product.name}: {item.qty_requested} шт.")

        msg = (
            "✔ <b>Заказ выдан клиенту</b>\n"
            f"Заказ: <b>#{order.id}</b>\n"
            f"Клиент: <b>{order.customer_name or '-'}</b>\n"
            f"Телефон: {order.customer_phone or '-'}\n\n" + "\n".join(items_text)
        )
        send_telegram_message(
            msg,
            factory_id=order.factory_id,
            include_manager_chats=False,
        )
    except Exception:
        pass

    flash(f"Заказ #{order.id} отмечен как выданный клиенту.", "success")
    return redirect(url_for("shop.list_shop_orders"))


def _get_daily_sales_chart_data(factory_id=None, days: int = 7):
    today = date.today()
    start_date = today - timedelta(days=days - 1)

    q = db.session.query(Sale, Product).join(Product, Product.id == Sale.product_id)

    if factory_id is not None:
        q = q.filter(Product.factory_id == factory_id)
    elif _is_shared_shop_user():
        if hasattr(Sale, "shop_id") and current_user.shop_id:
            q = q.filter(Sale.shop_id == current_user.shop_id)

    rows = q.all()

    totals_by_day = {}
    for i in range(days):
        d = start_date + timedelta(days=i)
        totals_by_day[d] = 0.0

    for sale, product in rows:
        raw_sale_date = getattr(sale, "date", None)

        if not raw_sale_date and hasattr(sale, "created_at"):
            raw_sale_date = getattr(sale, "created_at", None)

        if not raw_sale_date:
            continue

        if isinstance(raw_sale_date, datetime):
            s_date = raw_sale_date.date()
        else:
            s_date = raw_sale_date

        if s_date < start_date or s_date > today:
            continue

        totals_by_day[s_date] += _sale_amount_uzs(sale, product)

    labels = []
    values = []

    for i in range(days):
        d = start_date + timedelta(days=i)
        labels.append(d.strftime("%d.%m"))
        values.append(float(totals_by_day.get(d, 0.0) or 0.0))

    return labels, values


def _get_factory_sales_chart_data(factory_id=None):
    q = db.session.query(Sale, Product).join(Product, Product.id == Sale.product_id)

    if factory_id is not None:
        q = q.filter(Product.factory_id == factory_id)
    elif _is_shared_shop_user():
        if hasattr(Sale, "shop_id") and current_user.shop_id:
            q = q.filter(Sale.shop_id == current_user.shop_id)

    rows = q.all()

    by_factory = {}

    for sale, product in rows:
        fid = getattr(product, "factory_id", None)
        if not fid:
            continue

        factory_name = "-"
        if getattr(product, "factory", None) and getattr(product.factory, "name", None):
            factory_name = product.factory.name

        if fid not in by_factory:
            by_factory[fid] = {
                "factory_name": factory_name,
                "amount_uzs": 0.0,
            }

        by_factory[fid]["amount_uzs"] += _sale_amount_uzs(sale, product)

    sorted_rows = sorted(
        by_factory.values(),
        key=lambda x: x["amount_uzs"],
        reverse=True,
    )

    labels = [row["factory_name"] for row in sorted_rows]
    values = [float(row["amount_uzs"] or 0.0) for row in sorted_rows]

    return labels, values
