from datetime import datetime, timedelta, date

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    Response,
    jsonify,
    session,
)
from flask_login import login_required, current_user

from app.telegram_notify import send_telegram_message

from ..extensions import db
from ..auth_utils import roles_required
from ..models import (
    Product,
    Production,
    ShopStock,
    ShopOrder,
    ShopOrderItem,
    Movement,
    StockMovement,
    # Sale is needed for dashboard stats. If your model name differs, tell me.
    Sale,
)
from ..services.shop_service import ShopService


shop_bp = Blueprint("shop", __name__, url_prefix="/shop")
shop_service = ShopService()


# =========================
# Helpers (Shop dashboard)
# =========================

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


def _sum_shop_stock_value_uzs(factory_id: int) -> float:
    """
    Sums shop stock value using product.sell_price_per_item (assumed UZS).
    """
    rows = (
        db.session.query(ShopStock.quantity, Product.sell_price_per_item)
        .join(Product, Product.id == ShopStock.product_id)
        .filter(Product.factory_id == factory_id)
        .all()
    )
    total = 0.0
    for qty, price in rows:
        total += float(qty or 0) * float(price or 0)
    return total


def _sum_factory_stock_value_uzs(factory_id: int) -> float:
    """
    Sums factory stock value using Product.quantity * Product.sell_price_per_item (assumed UZS).
    """
    rows = (
        db.session.query(Product.quantity, Product.sell_price_per_item)
        .filter(Product.factory_id == factory_id)
        .all()
    )
    total = 0.0
    for qty, price in rows:
        total += float(qty or 0) * float(price or 0)
    return total


def _sale_amount_uzs(sale, product) -> float:
    """
    Robust: uses Sale.total_sell if present, otherwise quantity * sell_price_per_item.
    Treats as UZS for dashboard totals.
    """
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


def _get_sales_totals(factory_id: int):
    """
    Returns:
      yesterday_sales_uzs
      week_sales_uzs (last 7 days including today)
    Tries to filter by factory_id using:
      - Sale.factory_id if exists
      - else join Sale.product_id -> Product.factory_id
    Date uses:
      - Sale.date if exists
      - else Sale.created_at if exists
      - else falls back to 0
    """
    today = date.today()
    y = today - timedelta(days=1)
    week_start = today - timedelta(days=6)

    # Build base query
    q = db.session.query(Sale, Product).join(Product, Product.id == Sale.product_id)

    # Filter by factory
    if hasattr(Sale, "factory_id"):
        q = q.filter(Sale.factory_id == factory_id)
    else:
        q = q.filter(Product.factory_id == factory_id)

    sales = q.all()

    yesterday_total = 0.0
    week_total = 0.0

    for sale, product in sales:
        # Determine sale date
        s_date = None
        if hasattr(sale, "date") and sale.date:
            s_date = sale.date
        elif hasattr(sale, "created_at") and sale.created_at:
            try:
                s_date = sale.created_at.date()
            except Exception:
                s_date = None

        if not s_date:
            continue

        amt = _sale_amount_uzs(sale, product)

        if s_date == y:
            yesterday_total += amt

        if week_start <= s_date <= today:
            week_total += amt

    return yesterday_total, week_total


# =========================
# 0. SHOP DASHBOARD (HOME)
# =========================

@shop_bp.route("/dashboard", methods=["GET"])
@login_required
@roles_required("shop", "manager", "admin")
def dashboard_shop():
    factory_id = current_user.factory_id
    current_date = _get_current_date_for_lang()

    # Sales stats (UZS)
    try:
        yesterday_sales_uzs, week_sales_uzs = _get_sales_totals(factory_id=factory_id)
    except Exception:
        yesterday_sales_uzs, week_sales_uzs = 0.0, 0.0

    # Stock values (UZS)
    try:
        shop_uzs = _sum_shop_stock_value_uzs(factory_id=factory_id)
    except Exception:
        shop_uzs = 0.0

    try:
        factory_uzs = _sum_factory_stock_value_uzs(factory_id=factory_id)
    except Exception:
        factory_uzs = 0.0

    total_uzs = float(factory_uzs or 0) + float(shop_uzs or 0)

    # Orders summary
    shop_orders_pending = (
        ShopOrder.query
        .filter_by(factory_id=factory_id, status="pending")
        .count()
    )
    shop_orders_ready = (
        ShopOrder.query
        .filter_by(factory_id=factory_id, status="ready")
        .count()
    )

    # stats object for template compatibility
    class _Stats:
        def __init__(self, y, w):
            self.yesterday_sales_uzs = y
            self.week_sales_uzs = w

    stats = _Stats(yesterday_sales_uzs, week_sales_uzs)

    return render_template(
        "shop/dashboard_shop.html",
        stats=stats,
        shop_uzs=shop_uzs,
        factory_uzs=factory_uzs,
        total_uzs=total_uzs,
        shop_orders_pending=shop_orders_pending,
        shop_orders_ready=shop_orders_ready,
        current_date=current_date,
    )


# ---------- 1. СКЛАД МАГАЗИНА (ЛИСТ) ----------

@shop_bp.route("/", methods=["GET"])
@login_required
def list_shop():
    q_raw = request.args.get("q") or ""
    q = q_raw.strip()
    sort = request.args.get("sort", "name")

    data = shop_service.list_items(
        q=q or None,
        sort=sort,
        factory_id=current_user.factory_id,
    )

    return render_template(
        "shop/list.html",
        items=data["items"],
        total_qty=data["total_qty"],
        total_value_uzs=data["total_value_uzs"],
        q=q,
        sort=sort,
    )


# ---------- 2. ПЕРЕДАЧА С ФАБРИКИ В МАГАЗИН ----------

@shop_bp.route("/transfer", methods=["GET", "POST"])
@login_required
@roles_required("admin", "manager")
def transfer_to_shop():
    factory_id = current_user.factory_id

    if request.method == "POST":
        try:
            product_id = int(request.form.get("product_id") or 0)
            quantity = int(request.form.get("quantity") or 0)
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

        product = (
            Product.query
            .filter_by(id=product_id, factory_id=factory_id)
            .first()
        )
        if not product:
            flash("Товар не найден.", "danger")
            return redirect(url_for("shop.transfer_to_shop"))

        try:
            shop_service.transfer_to_shop(
                factory_id=factory_id,
                product_id=product.id,
                quantity=quantity,
                sell_price_per_item=sell_price_per_item,
            )
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("shop.transfer_to_shop"))

        move = Movement(
            factory_id=factory_id,
            product_id=product.id,
            source="factory",
            destination="shop",
            change=quantity,
            note=f"Фабрика передала в магазин {quantity} шт.",
            created_by_id=current_user.id,
            timestamp=datetime.utcnow(),
        )
        db.session.add(move)
        db.session.commit()

        flash("Товар успешно передан в магазин.", "success")
        return redirect(url_for("shop.list_shop"))

    mode = (request.args.get("mode") or "today").strip().lower()

    if mode == "all":
        products = (
            Product.query
            .filter_by(factory_id=factory_id)
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
                Product.query
                .filter(
                    Product.factory_id == factory_id,
                    Product.id.in_(produced_ids),
                )
                .order_by(Product.name.asc())
                .all()
            )
        else:
            products = (
                Product.query
                .filter(
                    Product.factory_id == factory_id,
                    Product.quantity > 0,
                )
                .order_by(Product.name.asc())
                .all()
            )

    return render_template(
        "shop/transfer.html",
        products=products,
        mode=mode,
    )


# ---------- 3. ЭКСПОРТ СКЛАДА МАГАЗИНА (XLSX) ----------

@shop_bp.route("/export", methods=["GET"])
@login_required
def export_shop():
    xlsx = shop_service.export_full_report_xlsx(
        factory_id=current_user.factory_id,
        q=request.args.get("q"),
        sort=request.args.get("sort", "name"),
    )

    return Response(
        xlsx,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=mini_moda_report.xlsx"
        },
    )


# ---------- 4. ЗАКАЗЫ МАГАЗИНА (СПИСОК) ----------

@shop_bp.route("/orders", methods=["GET"])
@login_required
@roles_required("shop", "manager", "admin")
def list_shop_orders():
    factory_id = current_user.factory_id
    status = (request.args.get("status") or "").strip().lower()

    query = ShopOrder.query.filter_by(factory_id=factory_id)

    if current_user.is_shop and not (current_user.is_manager or current_user.is_admin):
        query = query.filter(ShopOrder.created_by_id == current_user.id)

    if status in ("pending", "ready", "completed", "cancelled"):
        query = query.filter(ShopOrder.status == status)

    orders = query.order_by(ShopOrder.created_at.desc()).all()

    base_query = ShopOrder.query.filter_by(factory_id=factory_id)
    if current_user.is_shop and not (current_user.is_manager or current_user.is_admin):
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
    factory_id = current_user.factory_id

    order = (
        ShopOrder.query
        .filter_by(id=order_id, factory_id=factory_id)
        .first_or_404()
    )
    new_status = (request.form.get("status") or "").strip().lower()

    if new_status not in ("pending", "ready", "completed", "cancelled"):
        flash("Неверный статус заказа.", "warning")
        return redirect(url_for("shop.list_shop_orders"))

    if current_user.is_shop and not (current_user.is_manager or current_user.is_admin):
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
        ShopOrder.query
        .filter_by(factory_id=current_user.factory_id, status="pending")
        .order_by(ShopOrder.created_at.asc())
        .all()
    )
    return render_template("shop/orders_for_factory.html", orders=orders)


@shop_bp.route("/orders/item/<int:item_id>/ship", methods=["POST"])
@login_required
@roles_required("manager", "admin")
def ship_order_item(item_id: int):
    factory_id = current_user.factory_id

    item = (
        ShopOrderItem.query
        .join(Product, Product.id == ShopOrderItem.product_id)
        .filter(
            ShopOrderItem.id == item_id,
            Product.factory_id == factory_id,
        )
        .first_or_404()
    )

    order = item.order
    product = item.product

    try:
        ship_qty = int(request.form.get("ship_qty") or 0)
    except (TypeError, ValueError):
        ship_qty = 0

    if ship_qty <= 0:
        flash("Количество должно быть больше нуля.", "warning")
        return redirect(url_for("shop.factory_pending_orders"))

    if ship_qty > item.qty_remaining:
        flash("Нельзя отправить больше, чем осталось по заказу.", "danger")
        return redirect(url_for("shop.factory_pending_orders"))

    if product.quantity < ship_qty:
        flash("На фабрике нет такого количества на складе.", "danger")
        return redirect(url_for("shop.factory_pending_orders"))

    product.quantity -= ship_qty

    shop_row = ShopStock.query.filter_by(product_id=product.id).first()
    if not shop_row:
        shop_row = ShopStock(product_id=product.id, quantity=0)
        db.session.add(shop_row)

    shop_row.quantity += ship_qty

    item.qty_from_shop_now += ship_qty
    item.qty_remaining -= ship_qty

    order.recalc_status()

    move = Movement(
        factory_id=factory_id,
        product_id=product.id,
        source=f"factory (order #{order.id})",
        destination="shop",
        change=ship_qty,
        note=f"Отгружено в магазин {ship_qty} шт. по заказу #{order.id}",
        created_by_id=current_user.id,
        timestamp=datetime.utcnow(),
    )
    db.session.add(move)

    stock_mv = StockMovement(
        factory_id=factory_id,
        product_id=product.id,
        qty_change=ship_qty,
        source="factory",
        destination="shop",
        movement_type="factory_to_shop_for_order",
        order_id=order.id,
        comment=f"Shipped {ship_qty} pcs for order #{order.id} from factory to shop",
    )
    db.session.add(stock_mv)

    db.session.commit()

    flash(f"Отправлено в магазин {ship_qty} шт. для заказа #{order.id}.", "success")
    return redirect(url_for("shop.factory_pending_orders"))


@shop_bp.route("/history", methods=["GET"])
@login_required
def movement_history():
    factory_id = current_user.factory_id

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

    query = (
        StockMovement.query
        .join(Product)
        .filter(Product.factory_id == factory_id)
    )

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

    products = (
        Product.query
        .filter_by(factory_id=factory_id)
        .order_by(Product.name.asc())
        .all()
    )

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
    low = (
        ShopStock.query
        .join(Product)
        .filter(
            Product.factory_id == current_user.factory_id,
            ShopStock.quantity < 5,
        )
        .all()
    )
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
    order = (
        ShopOrder.query
        .filter_by(id=order_id, factory_id=current_user.factory_id)
        .first_or_404()
    )

    movements = (
        StockMovement.query
        .filter(
            StockMovement.order_id == order_id,
            StockMovement.factory_id == current_user.factory_id,
        )
        .order_by(StockMovement.timestamp.desc())
        .all()
    )

    return render_template(
        "history/order_movements.html",
        order=order,
        movements=movements,
    )


@shop_bp.route("/sell/<int:product_id>", methods=["GET", "POST"])
@login_required
@roles_required("shop", "manager", "admin")
def sell_product(product_id: int):
    factory_id = current_user.factory_id

    product = (
        Product.query
        .filter_by(id=product_id, factory_id=factory_id)
        .first_or_404()
    )
    stock = ShopStock.query.filter_by(product_id=product.id).first()
    available = stock.quantity if stock else 0

    if request.method == "POST":
        try:
            requested_qty = int(request.form.get("quantity") or 0)
        except ValueError:
            flash("Неверное количество.", "danger")
            return redirect(url_for("shop.sell_product", product_id=product.id))

        if requested_qty <= 0:
            flash("Количество должно быть больше нуля.", "warning")
            return redirect(url_for("shop.sell_product", product_id=product.id))

        customer_name = (request.form.get("customer_name") or "").strip() or None
        customer_phone = (request.form.get("customer_phone") or "").strip() or None
        note = (request.form.get("note") or "").strip() or None
        allow_partial_sale = bool(request.form.get("allow_partial_sale"))

        try:
            result = shop_service.sell_from_shop_or_create_order(
                factory_id=factory_id,
                product_id=product.id,
                requested_qty=requested_qty,
                customer_name=customer_name,
                customer_phone=customer_phone,
                note=note,
                allow_partial_sale=allow_partial_sale,
                created_by=current_user,
            )
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("shop.sell_product", product_id=product.id))

        sale = result["sale"]
        order = result["order"]
        missing = result["missing"]
        sold_now = result["sold_now"]

        if sale:
            mv = StockMovement(
                factory_id=factory_id,
                product_id=product.id,
                qty_change=-sale.quantity,
                source="shop",
                destination="customer",
                movement_type="shop_sale",
                order_id=order.id if order else None,
                comment=f"Продажа {sale.quantity} шт. клиенту {customer_name or ''}".strip(),
            )
            db.session.add(mv)
            db.session.commit()

            try:
                qty = sale.quantity
                currency = getattr(sale, "currency", None) or getattr(product, "currency", "UZS")

                if hasattr(sale, "total_sell") and sale.total_sell is not None:
                    total_sell = sale.total_sell
                else:
                    price = getattr(
                        sale,
                        "sell_price_per_item",
                        product.sell_price_per_item or 0,
                    )
                    total_sell = (qty or 0) * (price or 0)

                msg = (
                    "💸 <b>Новая продажа (магазин)</b>\n"
                    f"Модель: <b>{product.name}</b>\n"
                    f"Категория: {product.category or '-'}\n"
                    f"Кол-во: <b>{qty}</b> шт.\n"
                    f"Сумма: <b>{total_sell:.2f} {currency}</b>\n"
                    f"Клиент: {customer_name or '-'}"
                )
                send_telegram_message(msg)
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
                send_telegram_message(msg)
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
    )