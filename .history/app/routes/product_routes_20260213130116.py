import os
import math
from datetime import datetime
from io import BytesIO

import pandas as pd
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, or_

from ..extensions import db
from ..auth_utils import roles_required
from ..models import Product, ShopStock, Sale  # Sale must exist
from ..services.product_service import ProductService


products_bp = Blueprint("products", __name__, url_prefix="/products")
service = ProductService()


# ==========================
#   🔧 SMALL HELPERS
# ==========================

def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=None):
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
    if getattr(current_user, "is_superadmin", False):
        return current_user.factory_id

    if current_user.factory_id is None:
        flash("У пользователя не привязан цех (factory). Обратитесь к администратору.", "danger")
        return None

    return current_user.factory_id


def _safe_datetime(value) -> datetime:
    try:
        dt = pd.to_datetime(value, errors="coerce", dayfirst=True)
        if dt is None or pd.isna(dt):
            return datetime.utcnow()
        return dt.to_pydatetime()
    except Exception:
        return datetime.utcnow()


def allowed_file(filename: str) -> bool:
    allowed = current_app.config.get("ALLOWED_EXTENSIONS", {"xlsx"})
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


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

    query = (
        db.session.query(
            Product,
            func.coalesce(ShopStock.quantity, 0).label("qty_shop"),
        )
        .outerjoin(ShopStock, ShopStock.product_id == Product.id)
    )

    if not getattr(current_user, "is_superadmin", False):
        query = query.filter(Product.factory_id == factory_id)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Product.name.ilike(like),
                Product.category.ilike(like),
            )
        )

    if selected_category:
        query = query.filter(Product.category == selected_category)

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
        qty_factory = product.quantity or 0
        qty_shop_val = qty_shop or 0
        qty_total = qty_factory + qty_shop_val

        rows.append(
            {
                "p": product,
                "qty_factory": qty_factory,
                "qty_shop": qty_shop_val,
                "qty_total": qty_total,
            }
        )

    cat_query = db.session.query(Product.category).distinct()
    if not getattr(current_user, "is_superadmin", False):
        cat_query = cat_query.filter(Product.factory_id == factory_id)

    categories = [c[0] for c in cat_query.order_by(Product.category.asc()).all() if c[0]]

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

    # image upload (optional)
    file = request.files.get("image")
    image_path = None
    if file and file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext in {"png", "jpg", "jpeg", "webp"}:
            filename = secure_filename(file.filename)
            upload_dir = current_app.config.get("UPLOAD_FOLDER", "app/static/uploads/products")
            os.makedirs(upload_dir, exist_ok=True)
            save_path = os.path.join(upload_dir, filename)
            file.save(save_path)
            image_path = f"uploads/products/{filename}"
        else:
            flash("Недопустимый формат изображения.", "danger")

    service.add_product(
        factory_id=factory_id,
        name=name,
        category=category,
        quantity=quantity,
        cost_price_per_item=cost_price_per_item,
        sell_price_per_item=sell_price_per_item,
        currency=currency,
        image_path=image_path,
    )

    flash("Товар добавлен / обновлён.", "success")
    return redirect(url_for("products.list_products"))


# ==========================
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

    service.increase_stock(factory_id=factory_id, product_id=product_id, quantity=quantity)
    flash("Остаток на фабрике увеличен.", "success")
    return redirect(url_for("products.list_products"))


# ==========================
#   🧾 SELL DIRECT FROM FACTORY
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

    # Read bytes once (we will scan multiple sheets)
    data = file.read()
    bio = BytesIO(data)

    # ---------------------------------------------------------
    # 1) Try detect and import Dad "Реализация" format
    #    IMPORTANT: header is "Модел" (not "Модель")
    # ---------------------------------------------------------
    try:
        xls = pd.ExcelFile(bio)

        dad_df = None
        for sheet in xls.sheet_names:
            preview = pd.read_excel(xls, sheet_name=sheet, header=None, nrows=80).fillna("").astype(str)

            header_row = None
            for i in range(min(80, len(preview))):
                row_text = " ".join(preview.iloc[i].tolist()).strip().lower()
                # accept "модел" OR "модель"
                if (("модел" in row_text) or ("модель" in row_text)) and (("сони" in row_text) or ("soni" in row_text)) and (("нархи" in row_text) or ("цена" in row_text)) and (("число" in row_text) or ("дата" in row_text)):
                    header_row = i
                    break

            if header_row is None:
                continue

            candidate = pd.read_excel(xls, sheet_name=sheet, header=header_row)
            candidate.columns = [str(c).strip().lower() for c in candidate.columns]

            has_model = ("модел" in candidate.columns) or ("модель" in candidate.columns)
            has_qty = ("сони" in candidate.columns) or ("soni" in candidate.columns)
            has_price = ("нархи" in candidate.columns) or ("цена" in candidate.columns)
            has_date = ("число" in candidate.columns) or ("дата" in candidate.columns)

            if has_model and has_qty and has_price and has_date:
                dad_df = candidate
                break

        if dad_df is not None:
            return _import_dad_sales_excel(dad_df, factory_id)

    except Exception:
        # If dad detection fails, continue with normal product import
        pass

    # ---------------------------------------------------------
    # 2) Normal product import (existing flexible mapping)
    # ---------------------------------------------------------
    try:
        bio.seek(0)
        df = pd.read_excel(bio, sheet_name=0)
    except Exception as e:
        flash(f"Could not read Excel file: {e}", "danger")
        return redirect(url_for("products.list_products"))

    df.columns = [str(c).strip().lower() for c in df.columns]

    col_map = {
        "name": ["name", "model", "модель", "модел", "номи", "наименование"],
        "category": ["category", "категория", "группа", "тип"],
        "quantity": ["quantity", "qty", "количество", "soni", "сони", "шт"],
        "cost": ["cost", "cost_price", "себестоимость", "закупка", "себестоимость за 1"],
        "sell": ["sell", "sell_price", "цена", "цена продажи", "продажа за 1"],
        "currency": ["currency", "валюта", "валюта товара"],
    }

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
    try:
        for _, row in df.iterrows():
            name = str(row.get(name_col, "")).strip()
            if not name or name.lower() == "nan":
                continue

            raw_qty = row.get(qty_col, 0)
            try:
                quantity = 0 if (isinstance(raw_qty, float) and math.isnan(raw_qty)) else int(raw_qty)
            except Exception:
                quantity = 0

            category = None
            if category_col:
                category = str(row.get(category_col, "")).strip() or None

            cost_price = _to_float(row.get(cost_col), default=None) if cost_col else None
            sell_price = _to_float(row.get(sell_col), default=None) if sell_col else None

            currency = "UZS"
            if currency_col:
                cur_val = str(row.get(currency_col, "")).strip().upper()
                if cur_val in ("UZS", "USD"):
                    currency = cur_val

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
    except Exception as e:
        db.session.rollback()
        flash(f"Import failed: {e}", "danger")
        return redirect(url_for("products.list_products"))


def _import_dad_sales_excel(df: pd.DataFrame, factory_id: int):
    """
    Dad 'Реализация' import as SALES.
    Headers in your real file are: Число | Модел | Сони | Нархи | Сумма
    IMPORTANT: column is 'Модел' (no ь), so we accept both.
    """
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    name_col = "модел" if "модел" in df.columns else "модель"
    qty_col = "сони" if "сони" in df.columns else "soni"
    price_col = "нархи" if "нархи" in df.columns else "цена"
    date_col = "число" if "число" in df.columns else "дата"

    sales_created = 0
    skipped = 0

    try:
        for _, row in df.iterrows():
            model = str(row.get(name_col, "")).strip()
            if not model or model.lower() == "nan":
                continue

            qty = _to_int(row.get(qty_col, 0), default=0)
            price = _to_int(_to_float(row.get(price_col, 0), default=0), default=0)

            if qty <= 0 or price <= 0:
                skipped += 1
                continue

            sold_at = _safe_datetime(row.get(date_col))

            # Ensure product exists
            product = Product.query.filter_by(factory_id=factory_id, name=model).first()
            if not product:
                product = Product(factory_id=factory_id, name=model, category=None)
                db.session.add(product)
                db.session.flush()

            # Shop stock (sell only what exists)
            stock = ShopStock.query.filter_by(factory_id=factory_id, product_id=product.id).first()
            available = int(stock.quantity) if stock and stock.quantity is not None else 0
            sell_qty = min(qty, available)

            if sell_qty <= 0:
                continue

            # Create sale (adjust field names if your Sale model differs)
            sale = Sale(
                factory_id=factory_id,
                product_id=product.id,
                quantity=sell_qty,          # if your field is "qty", rename to qty=sell_qty
                price_uzs=price,            # if different, rename
                total_uzs=sell_qty * price, # if different, rename
                sold_at=sold_at,
                created_by_id=current_user.id,
            )
            db.session.add(sale)

            # Decrease shop stock
            if stock:
                stock.quantity = available - sell_qty

            sales_created += 1

        db.session.commit()
        flash(f"Dad Excel imported ✅ Sales: {sales_created} (skipped rows: {skipped})", "success")
        return redirect(url_for("sales.list_sales"))

    except Exception as e:
        db.session.rollback()
        flash(f"Dad Excel import failed: {e}", "danger")
        return redirect(url_for("products.list_products"))


# ==========================
#   🔁 TRANSFER TO SHOP
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
        service.transfer_to_shop(factory_id=factory_id, product_id=product_id, quantity=quantity)
        flash("Товар передан в магазин.", "success")
    except ValueError as e:
        flash(str(e), "danger")

    return redirect(url_for("products.list_products"))


# ==========================
#   🏭 FACTORY STOCK OVERVIEW
# ==========================
@products_bp.route("/factory-stock")
@login_required
def factory_stock():
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
    product = Product.query.get_or_404(product_id)
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

        fabric_price_per_unit = f("fabric_price_per_unit")
        fabric_used_qty = f("fabric_used_qty")
        pieces_from_batch = f("pieces_from_batch", 0.0)

        sewing_cost_per_piece = f("sewing_cost_per_piece")

        pack_hanger_cost = f("pack_hanger_cost")
        pack_plastic_cost = f("pack_plastic_cost")
        pack_other_cost = f("pack_other_cost")

        fabric_cost_per_piece = 0.0
        if fabric_price_per_unit > 0 and fabric_used_qty > 0 and pieces_from_batch > 0:
            fabric_cost_per_piece = (fabric_price_per_unit * fabric_used_qty) / pieces_from_batch

        pack_cost_per_piece = pack_hanger_cost + pack_plastic_cost + pack_other_cost
        total_cost_per_piece = fabric_cost_per_piece + sewing_cost_per_piece + pack_cost_per_piece

        product.cost_price_per_item = total_cost_per_piece
        db.session.commit()

        flash("Себестоимость сохранена.", "success")
        return redirect(url_for("products.list_products"))

    return render_template("products/product_cost.html", product=product, cost_data=cost_data)
