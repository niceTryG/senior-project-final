from datetime import datetime

from flask import Blueprint, render_template, request, flash, url_for, redirect
from flask_login import login_required, current_user

from ..auth_utils import roles_required
from ..extensions import db
from ..models import Sale, Product
from ..services.shop_service import ShopService

from app.extensions import db
from app.models import Product, Sale, ShopStock, ShopOrder

sales_bp = Blueprint("sales", __name__, url_prefix="/sales")

# сервис магазина (логика склада + продаж/заказов)
shop_service = ShopService()

@sales_bp.route("/import-dad-excel", methods=["GET", "POST"])
@login_required
def import_dad_excel():
    if request.method == "GET":
        return render_template("sales/import_dad_excel.html")

    file = request.files.get("file")
    if not file:
        flash("Файл не выбран", "warning")
        return redirect(url_for("sales.import_dad_excel"))

    factory_id = current_user.factory_id
    if not factory_id:
        flash("Ошибка: у пользователя нет factory_id", "danger")
        return redirect(url_for("main.dashboard"))

    try:
        df = pd.read_excel(file, sheet_name=0, header=None)

        # 🔎 find header row (where 'Модель' appears)
        header_row = None
        for i in range(15):
            row = df.iloc[i].astype(str).str.lower()
            if "модель" in " ".join(row.values):
                header_row = i
                break

        if header_row is None:
            raise ValueError("Не найдена таблица 'Реализация'")

        df = pd.read_excel(file, sheet_name=0, header=header_row)
        df.columns = [str(c).strip().lower() for c in df.columns]

        created_sales = 0
        created_orders = 0

        for _, row in df.iterrows():
            model = str(row.get("модель", "")).strip()
            if not model or model.lower() == "nan":
                continue

            qty = int(row.get("сони", 0) or 0)
            price = int(row.get("нархи", 0) or 0)
            raw_date = row.get("число")

            if qty <= 0 or price <= 0:
                continue

            # 🗓 date parsing (Excel is messy)
            if isinstance(raw_date, datetime):
                sold_at = raw_date
            else:
                try:
                    sold_at = pd.to_datetime(raw_date, dayfirst=True)
                except Exception:
                    sold_at = datetime.utcnow()

            # 🔍 product
            product = Product.query.filter_by(
                factory_id=factory_id,
                name=model
            ).first()

            if not product:
                product = Product(
                    factory_id=factory_id,
                    name=model,
                    cost_uzs=price
                )
                db.session.add(product)
                db.session.flush()

            # 🏪 shop stock
            stock = ShopStock.query.filter_by(
                factory_id=factory_id,
                product_id=product.id
            ).first()

            available = stock.qty if stock else 0

            if available < qty:
                order = ShopOrder(
                    factory_id=factory_id,
                    product_id=product.id,
                    qty=qty - available,
                    status="pending",
                    created_by_id=current_user.id
                )
                db.session.add(order)
                created_orders += 1
                sold_qty = available
            else:
                sold_qty = qty

            # 💰 sale
            if sold_qty > 0:
                sale = Sale(
                    factory_id=factory_id,
                    product_id=product.id,
                    qty=sold_qty,
                    price_uzs=price,
                    total_uzs=sold_qty * price,
                    sold_at=sold_at,
                    created_by_id=current_user.id
                )
                db.session.add(sale)

                if stock:
                    stock.qty -= sold_qty

                created_sales += 1

        db.session.commit()
        flash(
            f"Импорт завершён ✅ Продажи: {created_sales}, Заказы: {created_orders}",
            "success"
        )
        return redirect(url_for("sales.list_sales"))

    except Exception as e:
        db.session.rollback()
        flash(f"Ошибка импорта: {e}", "danger")
        return redirect(url_for("sales.import_dad_excel"))

@sales_bp.route("/", methods=["GET"])
@login_required
@roles_required("admin", "manager")
def list_sales():
    q = request.args.get("q", "").strip()
    date_from_str = request.args.get("from", "").strip()
    date_to_str = request.args.get("to", "").strip()

    date_from = None
    date_to = None
    date_fmt = "%Y-%m-%d"

    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, date_fmt).date()
        except ValueError:
            date_from = None

    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, date_fmt).date()
        except ValueError:
            date_to = None

    # base query: только продажи по товарам текущей фабрики
    query = (
        Sale.query
        .join(Product)
        .filter(Product.factory_id == current_user.factory_id)
    )

    # text search: customer, phone, product name, category
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            db.or_(
                db.func.lower(Sale.customer_name).like(like),
                db.func.lower(Sale.customer_phone).like(like),
                db.func.lower(Product.name).like(like),
                db.func.lower(db.func.coalesce(Product.category, "")).like(like),
            )
        )

    # date filters
    if date_from:
        query = query.filter(Sale.date >= date_from)
    if date_to:
        query = query.filter(Sale.date <= date_to)

    sales = query.order_by(Sale.date.desc(), Sale.id.desc()).all()

    # totals by currency
    totals: dict[str, dict[str, float]] = {}
    for s in sales:
        cur = s.currency or "UZS"
        if cur not in totals:
            totals[cur] = {"sell": 0.0, "cost": 0.0, "profit": 0.0}
        totals[cur]["sell"] += s.total_sell
        totals[cur]["cost"] += s.total_cost
        totals[cur]["profit"] += s.profit

    return render_template(
        "sales/list.html",
        sales=sales,
        q=q,
        date_from=date_from_str,
        date_to=date_to_str,
        totals=totals,
    )


@sales_bp.route("/shop/sell", methods=["GET", "POST"])
@login_required
def shop_sell():
    # допускаем только роль магазина / менеджера / админа
    if not (current_user.is_shop or current_user.is_manager or current_user.is_admin):
        flash("У вас нет доступа к этому разделу.", "danger")
        return redirect(url_for("main.dashboard"))

    factory_id = current_user.factory_id

    # список товаров только этой фабрики
    products = (
        Product.query
        .filter_by(factory_id=factory_id)
        .order_by(Product.name.asc())
        .all()
    )

    if request.method == "POST":
        # безопасный парсинг product_id
        try:
            product_id = int(request.form.get("product_id"))
        except (TypeError, ValueError):
            flash("Неверный товар.", "warning")
            return redirect(url_for("sales.shop_sell"))

        # безопасный парсинг количества
        try:
            qty = int(request.form.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0

        customer_name = request.form.get("customer_name") or None
        customer_phone = request.form.get("customer_phone") or None
        note = request.form.get("note") or None
        allow_partial = bool(request.form.get("allow_partial"))

        if qty <= 0:
            flash("Количество должно быть больше нуля.", "warning")
            return redirect(url_for("sales.shop_sell"))

        try:
            result = shop_service.sell_from_shop_or_create_order(
                factory_id=factory_id,
                product_id=product_id,
                requested_qty=qty,
                customer_name=customer_name,
                customer_phone=customer_phone,
                note=note,
                allow_partial_sale=allow_partial,
                created_by=current_user,
            )
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("sales.shop_sell"))

        sold_now = result["sold_now"]
        missing = result["missing"]

        if sold_now > 0 and missing == 0:
            flash(f"Продано {sold_now} шт. из магазина (хватило остатка).", "success")
        elif sold_now > 0 and missing > 0:
            flash(
                f"Продано сейчас {sold_now} шт. из магазина. "
                f"Создан заказ на оставшиеся {missing} шт.",
                "info",
            )
        elif sold_now == 0 and missing > 0:
            flash(
                f"В магазине нет достаточного количества. "
                f"Создан заказ на {missing} шт.",
                "info",
            )
        else:
            flash("Операция завершена.", "info")

        if current_user.is_shop:
            return redirect(url_for("shop.list_shop"))
        return redirect(url_for("sales.list_sales"))

    return render_template("sales/shop_sell.html", products=products)
