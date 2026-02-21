import os
from werkzeug.utils import secure_filename
from flask import current_app
from flask import Blueprint, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime
import pandas as pd

from app.extensions import db
from app.decorators import roles_required
from app.models import Product, Sale, ShopStock, ShopOrder
from app.utils.factory import _ensure_factory_bound

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from flask_login import login_required, current_user
from sqlalchemy import func, or_
import math

from ..auth_utils import roles_required
from ..models import Product, ShopStock
from ..extensions import db
from ..services.product_service import ProductService


products_bp = Blueprint("products", __name__, url_prefix="/products")
service = ProductService()


# ==========================
#   🔧 SMALL HELPERS
# ==========================

def _to_int(value, default: int = 0) -> int:
    """Safely convert to int, return default on error or None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float = None):
    """Safely convert to float, return default on error/None/empty."""
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
        if not value:
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ensure_factory_bound():
    """
    Ensure user has factory_id or is superadmin.
    Returns factory_id OR None if superadmin.
    If invalid → flashes and returns redirect response.
    """
    if getattr(current_user, "is_superadmin", False):
        # superadmin can see all factories; factory_id may be None
        return current_user.factory_id

    if current_user.factory_id is None:
        flash("У пользователя не привязан цех (factory). Обратитесь к администратору.", "danger")
        return None

    return current_user.factory_id


# ==========================
#   📦 PRODUCT LIST
# ==========================
@products_bp.route("/")
@login_required
def list_products():
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "name")
    selected_category = (request.args.get("category") or "").strip() or None

    factory_id = current_user.factory_id

    # Base query: product + shop stock
    query = (
        db.session.query(
            Product,
            func.coalesce(ShopStock.quantity, 0).label("qty_shop"),
        )
        .outerjoin(ShopStock, ShopStock.product_id == Product.id)
    )

    # Multi-factory scoping:
    # - normal users → only their factory
    # - superadmin (factory_id is None + is_admin) → see all
    if not getattr(current_user, "is_superadmin", False):
        query = query.filter(Product.factory_id == factory_id)

    # Search by name / category substring
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Product.name.ilike(like),
                Product.category.ilike(like),
            )
        )

    # Filter by exact category (from dropdown)
    if selected_category:
        query = query.filter(Product.category == selected_category)

    # Sorting
    if sort == "name":
        query = query.order_by(Product.name.asc())
    elif sort == "qty_total":
        query = query.order_by(
            (Product.quantity + func.coalesce(ShopStock.quantity, 0)).desc()
        )
    elif sort == "qty_factory":
        query = query.order_by(Product.quantity.desc())
    elif sort == "qty_shop":
        query = query.order_by(func.coalesce(ShopStock.quantity, 0).desc())
    else:
        query = query.order_by(Product.name.asc())

    rows = []
    for product, qty_shop in query.all():
        qty_factory = product.quantity or 0          # фабрика = Product.quantity
        qty_shop_val = qty_shop or 0                 # магазин = ShopStock.quantity
        qty_total = qty_factory + qty_shop_val       # всего = фабрика + магазин

        rows.append(
            {
                "p": product,
                "qty_factory": qty_factory,
                "qty_shop": qty_shop_val,
                "qty_total": qty_total,
            }
        )

    # Categories for dropdown (distinct, non-empty)
    cat_query = db.session.query(Product.category).distinct()
    if not getattr(current_user, "is_superadmin", False):
        cat_query = cat_query.filter(Product.factory_id == factory_id)

    categories = [
        c[0] for c in cat_query.order_by(Product.category.asc()).all()
        if c[0]
    ]

    return render_template(
        "products/list.html",
        products=rows,
        q=q,
        sort=sort,
        categories=categories,
        selected_category=selected_category,
    )


# ==========================
#   ➕ ADD PRODUCT
# ==========================
@products_bp.route("/add", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def add_product():
    factory_id = _ensure_factory_bound()
    if factory_id is None and not getattr(current_user, "is_superadmin", False):
        return redirect(url_for("products.list_products"))

    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip() or None

    quantity = _to_int(request.form.get("quantity", "0"), default=0)
    if quantity < 0:
        quantity = 0

    cost_price_per_item = _to_float(request.form.get("cost_price_per_item"), default=None)
    sell_price_per_item = _to_float(request.form.get("sell_price_per_item"), default=None)

    currency = (request.form.get("currency", "UZS") or "UZS").strip()

    if not name:
        flash("Название модели обязательно.", "warning")
        return redirect(url_for("products.list_products"))

    # ============================
    # 🔥 IMAGE UPLOAD (NEW PART)
    # ============================
    file = request.files.get("image")
    image_path = None

    if file and file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
        allowed = {"png", "jpg", "jpeg", "webp"}

        if ext in allowed:
            filename = secure_filename(file.filename)

            upload_dir = current_app.config.get(
                "UPLOAD_FOLDER", "app/static/uploads/products"
            )

            os.makedirs(upload_dir, exist_ok=True)

            save_path = os.path.join(upload_dir, filename)
            file.save(save_path)

            # store ONLY the relative path (for url_for('static'))
            image_path = f"uploads/products/{filename}"
        else:
            flash("Недопустимый формат изображения.", "danger")

    # ============================
    # SAVE PRODUCT WITH IMAGE
    # ============================
    service.add_product(
        factory_id=factory_id,
        name=name,
        category=category,
        quantity=quantity,
        cost_price_per_item=cost_price_per_item,
        sell_price_per_item=sell_price_per_item,
        currency=currency,
        image_path=image_path,  # ← ADDED THIS PARAM
    )

    flash("Товар добавлен / обновлён.", "success")
    return redirect(url_for("products.list_products"))

#   ➕ ADD STOCK (FACTORY)
# ==========================
@products_bp.route("/<int:product_id>/add_stock", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def add_stock(product_id: int):
    factory_id = _ensure_factory_bound()
    if factory_id is None and not getattr(current_user, "is_superadmin", False):
        return redirect(url_for("products.list_products"))

    quantity = _to_int(request.form.get("quantity", "0"), default=0)
    if quantity <= 0:
        flash("Количество должно быть больше нуля.", "warning")
        return redirect(url_for("products.list_products"))

    service.increase_stock(
        factory_id=factory_id,
        product_id=product_id,
        quantity=quantity,
    )
    flash("Остаток на фабрике увеличен.", "success")
    return redirect(url_for("products.list_products"))


# ==========================
#   🧾 SELL DIRECT FROM FACTORY (RARE)
# ==========================
@products_bp.route("/<int:product_id>/sell", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def sell(product_id: int):
    factory_id = _ensure_factory_bound()
    if factory_id is None and not getattr(current_user, "is_superadmin", False):
        return redirect(url_for("products.list_products"))

    quantity = _to_int(request.form.get("quantity", "0"), default=0)
    if quantity <= 0:
        flash("Количество должно быть больше нуля.", "warning")
        return redirect(url_for("products.list_products"))

    sell_price_override = _to_float(request.form.get("sell_price_per_item"), default=None)

    customer_name = request.form.get("customer_name", "").strip() or None
    customer_phone = request.form.get("customer_phone", "").strip() or None

    try:
        service.sell_product(
            factory_id=factory_id,
            product_id=product_id,
            quantity=quantity,
            customer_name=customer_name,
            customer_phone=customer_phone,
            sell_price_override=sell_price_override,
        )
        flash("Продажа с фабрики зарегистрирована.", "success")
    except ValueError as e:
        flash(str(e), "danger")

    return redirect(url_for("products.list_products"))


# ==========================
#   📥 IMPORT FROM EXCEL
# ==========================
@products_bp.route("/import", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def import_products():
    factory_id = _ensure_factory_bound()
    if factory_id is None:
        flash("Factory is not selected.", "danger")
        return redirect(url_for("products.list_products"))

    file = request.files.get("file")
    if not file or file.filename == "":
        flash("No file selected for import.", "danger")
        return redirect(url_for("products.list_products"))

    try:
        df = pd.read_excel(file)
    except Exception as e:
        flash(f"Could not read Excel file: {e}", "danger")
        return redirect(url_for("products.list_products"))

    # normalize column names
    df.columns = [str(c).strip().lower() for c in df.columns]

    # =========================================================
    # 1️⃣ Detect DAD Excel (Реализация)
    # =========================================================
    is_dad_excel = (
        "модель" in df.columns and
        ("сони" in df.columns or "soni" in df.columns) and
        ("нархи" in df.columns or "цена" in df.columns) and
        ("число" in df.columns or "дата" in df.columns)
    )

    if is_dad_excel:
        return _import_dad_sales_excel(df, factory_id)

    # =========================================================
    # 2️⃣ NORMAL PRODUCT IMPORT (existing logic, simplified)
    # =========================================================
    name_cols = ["name", "model", "модель", "наименование"]
    qty_cols = ["quantity", "qty", "количество", "сони", "soni"]

    name_col = next((c for c in name_cols if c in df.columns), None)
    qty_col = next((c for c in qty_cols if c in df.columns), None)

    if not name_col or not qty_col:
        flash("Excel must contain at least columns for product name and quantity.", "danger")
        return redirect(url_for("products.list_products"))

    created = 0
    updated = 0

    try:
        for _, row in df.iterrows():
            name = str(row.get(name_col, "")).strip()
            if not name:
                continue

            try:
                qty = int(row.get(qty_col, 0) or 0)
            except Exception:
                qty = 0

            product = Product.query.filter_by(
                factory_id=factory_id,
                name=name
            ).first()

            if not product:
                product = Product(factory_id=factory_id, name=name)
                db.session.add(product)
                db.session.flush()
                created += 1
            else:
                updated += 1

            stock = ShopStock.query.filter_by(
                factory_id=factory_id,
                product_id=product.id
            ).first()

            if not stock:
                stock = ShopStock(
                    factory_id=factory_id,
                    product_id=product.id,
                    qty=qty
                )
                db.session.add(stock)
            else:
                stock.qty += qty

        db.session.commit()
        flash(f"Import completed ✅ Created: {created}, Updated: {updated}", "success")
        return redirect(url_for("products.list_products"))

    except Exception as e:
        db.session.rollback()
        flash(f"Import failed: {e}", "danger")
        return redirect(url_for("products.list_products"))


# =========================================================
# 🔥 DAD EXCEL IMPORTER (РЕАЛИЗАЦИЯ)
# =========================================================
def _import_dad_sales_excel(df, factory_id):
    """
    Imports Dad Excel as SALES.
    Columns: Число | Модель | Сони | Нархи | Сумма
    """

    name_col = "модель"
    qty_col = "сони" if "сони" in df.columns else "soni"
    price_col = "нархи" if "нархи" in df.columns else "цена"
    date_col = "число" if "число" in df.columns else "дата"

    sales_created = 0
    orders_created = 0

    try:
        for _, row in df.iterrows():
            name = str(row.get(name_col, "")).strip()
            if not name or name.lower() == "nan":
                continue

            try:
                qty = int(row.get(qty_col, 0) or 0)
                price = int(float(row.get(price_col, 0) or 0))
            except Exception:
                continue

            if qty <= 0 or price <= 0:
                continue

            # date
            raw_date = row.get(date_col)
            sold_at = pd.to_datetime(raw_date, errors="coerce")
            if sold_at is None or pd.isna(sold_at):
                sold_at = datetime.utcnow()
            else:
                sold_at = sold_at.to_pydatetime()

            # product
            product = Product.query.filter_by(
                factory_id=factory_id,
                name=name
            ).first()

            if not product:
                product = Product(factory_id=factory_id, name=name)
                db.session.add(product)
                db.session.flush()

            # shop stock
            stock = ShopStock.query.filter_by(
                factory_id=factory_id,
                product_id=product.id
            ).first()

            available = stock.qty if stock else 0
            sell_qty = min(qty, available)

            if available < qty:
                order = ShopOrder(
                    factory_id=factory_id,
                    customer_name="Excel import",
                    customer_phone="-",
                    note=f"Auto order for {name}",
                    status="pending",
                    created_by_id=current_user.id
                )
                db.session.add(order)
                orders_created += 1

            if sell_qty > 0:
                sale = Sale(
                    factory_id=factory_id,
                    product_id=product.id,
                    qty=sell_qty,
                    price_uzs=price,
                    total_uzs=sell_qty * price,
                    sold_at=sold_at,
                    created_by_id=current_user.id
                )
                db.session.add(sale)

                if stock:
                    stock.qty -= sell_qty

                sales_created += 1

        db.session.commit()
        flash(
            f"Dad Excel imported ✅ Sales: {sales_created}, Orders: {orders_created}",
            "success"
        )
        return redirect(url_for("sales.list_sales"))

    except Exception as e:
        db.session.rollback()
        flash(f"Dad Excel import failed: {e}", "danger")
        return redirect(url_for("products.list_products"))

    def find_col(key: str):
        for candidate in col_map.get(key, []):
            if candidate in df.columns:
                return candidate
        return None

    name_col = find_col("name")
    qty_col = find_col("quantity")

    if not name_col or not qty_col:
        flash("Excel must contain at least columns for product name and quantity.", "danger")
        return redirect(url_for("products.list_products"))

    category_col = find_col("category")
    cost_col = find_col("cost")
    sell_col = find_col("sell")
    currency_col = find_col("currency")

    imported = 0

    for _, row in df.iterrows():
        name = str(row.get(name_col, "")).strip()
        if not name:
            continue

        # quantity
        raw_qty = row.get(qty_col, 0)
        try:
            if isinstance(raw_qty, float) and math.isnan(raw_qty):
                quantity = 0
            else:
                quantity = int(raw_qty)
        except Exception:
            quantity = 0

        # category
        category = None
        if category_col:
            category_val = row.get(category_col, "")
            category = str(category_val).strip() or None

        # cost & sell
        cost_price = _to_float(row.get(cost_col), default=None) if cost_col else None
        sell_price = _to_float(row.get(sell_col), default=None) if sell_col else None

        # currency
        currency = "UZS"
        if currency_col:
            cur_val = str(row.get(currency_col, "")).strip().upper()
            if cur_val in ("UZS", "USD"):
                currency = cur_val

        # use your smart add_product -> will merge if same model/category/currency
        service.add_product(
            factory_id=factory_id,
            name=name,
            category=category,
            quantity=quantity,
            cost_price_per_item=cost_price,
            sell_price_per_item=sell_price,
            currency=currency,
        )
        imported += 1

    flash(f"Imported/updated {imported} products from Excel.", "success")
    return redirect(url_for("products.list_products"))


# ==========================
#   🔁 TRANSFER TO SHOP (LEGACY SHORTCUT)
# ==========================
@products_bp.route("/<int:product_id>/to_shop", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def to_shop(product_id: int):
    factory_id = _ensure_factory_bound()
    if factory_id is None and not getattr(current_user, "is_superadmin", False):
        return redirect(url_for("products.list_products"))

    quantity = _to_int(request.form.get("quantity", "0"), default=0)
    if quantity <= 0:
        flash("Количество должно быть больше нуля.", "warning")
        return redirect(url_for("products.list_products"))

    try:
        service.transfer_to_shop(
            factory_id=factory_id,
            product_id=product_id,
            quantity=quantity,
        )
        flash("Товар передан в магазин (через старый путь).", "success")
    except ValueError as e:
        flash(str(e), "danger")

    return redirect(url_for("products.list_products"))


# ==========================
#   🏭 FACTORY STOCK OVERVIEW
# ==========================
@products_bp.route("/factory-stock")
@login_required
def factory_stock():
    """
    Обзор склада фабрики:
    - qty_factory  = Product.quantity
    - qty_shop     = ShopStock.quantity (если есть запись)
    """
    factory_id = current_user.factory_id

    query = (
        db.session.query(
            Product.id,
            Product.name.label("name"),
            Product.quantity.label("qty_factory"),
            func.coalesce(ShopStock.quantity, 0).label("qty_shop"),
        )
        .outerjoin(ShopStock, ShopStock.product_id == Product.id)
    )

    if not getattr(current_user, "is_superadmin", False):
        query = query.filter(Product.factory_id == factory_id)

    rows = query.order_by(Product.name.asc()).all()

    products = []
    chart_labels = []
    chart_values = []

    for row in rows:
        qty_factory = row.qty_factory or 0
        qty_shop = row.qty_shop or 0
        qty_total = qty_factory + qty_shop

        products.append(
            {
                "id": row.id,
                "name": row.name,
                "qty_factory": qty_factory,
                "qty_shop": qty_shop,
                "qty_total": qty_total,
            }
        )

        # для графиков берём только товары, где на фабрике что-то есть
        if qty_factory > 0:
            chart_labels.append(row.name)
            chart_values.append(qty_factory)

    return render_template(
        "products/factory_stock.html",
        products=products,
        chart_labels=chart_labels,
        chart_values=chart_values,
    )


# ==========================
#   💸 COST CALCULATION
# ==========================
@products_bp.route("/<int:product_id>/cost", methods=["GET", "POST"])
@login_required
def product_cost(product_id: int):
    """
    Страница расчёта себестоимости для модели.
    FIXME/idea: позже можно связать с тканями и реальными партиями.
    """
    product = Product.query.get_or_404(product_id)

    # на будущее можно грузить из БД, пока пусто
    cost_data = {}

    if request.method == "POST":
        def f(name: str, default: float = 0.0) -> float:
            raw = request.form.get(name, "").strip().replace(",", ".")
            if raw == "":
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        # --- читаем все поля формы ---
        fabric_price_per_unit = f("fabric_price_per_unit")   # цена ткани за 1 кг/м
        fabric_used_qty       = f("fabric_used_qty")         # сколько кг/м ушло
        pieces_from_batch     = f("pieces_from_batch", 0.0)  # сколько штук из этой ткани

        sewing_cost_per_piece = f("sewing_cost_per_piece")   # пошив за 1 шт.

        pack_hanger_cost      = f("pack_hanger_cost")        # вешалка за 1 шт.
        pack_plastic_cost     = f("pack_plastic_cost")       # пакет/плёнка за 1 шт.
        pack_other_cost       = f("pack_other_cost")         # этикетка и т.п.

        # --- считаем ткань на 1 шт. ---
        fabric_cost_per_piece = 0.0
        if fabric_price_per_unit > 0 and fabric_used_qty > 0 and pieces_from_batch > 0:
            fabric_cost_per_piece = (fabric_price_per_unit * fabric_used_qty) / pieces_from_batch

        # упаковка на 1 шт.
        pack_cost_per_piece = pack_hanger_cost + pack_plastic_cost + pack_other_cost

        # итоговая себестоимость
        total_cost_per_piece = fabric_cost_per_piece + sewing_cost_per_piece + pack_cost_per_piece

        # --- сохраняем в продукт ---
        product.cost_price_per_item = total_cost_per_piece
        db.session.commit()

        flash("Себестоимость сохранена.", "success")
        return redirect(url_for("products.list_products"))

    # GET-запрос — просто показываем форму
    return render_template(
        "products/product_cost.html",
        product=product,
        cost_data=cost_data,
    )
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config["ALLOWED_EXTENSIONS"]
