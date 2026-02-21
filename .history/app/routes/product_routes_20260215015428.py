import os
import math
import hashlib
from io import BytesIO
from datetime import datetime, date

import pandas as pd
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from sqlalchemy.inspection import inspect as sa_inspect

from ..extensions import db
from ..auth_utils import roles_required
from ..services.product_service import ProductService
from ..models import (
    Product,
    ShopStock,
    Sale,
    CashRecord,
    StockMovement,
    ExcelImportRow,
)


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
    # superadmin can see all (factory_id may be None)
    if getattr(current_user, "is_superadmin", False):
        return current_user.factory_id

    if current_user.factory_id is None:
        flash("У пользователя не привязан цех (factory). Обратитесь к администратору.", "danger")
        return None

    return current_user.factory_id


def _norm(x) -> str:
    return str(x).strip().lower()


def _clean_int(x) -> int:
    """
    Handles numbers like: "60 000", "60000", "60,000", 60000.0
    """
    if x is None:
        return 0
    if isinstance(x, str):
        x = x.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
        if not x:
            return 0
    try:
        return int(float(x))
    except Exception:
        return 0


def _safe_excel_datetime(x):
    """
    Parses Excel date values safely. Returns python datetime or None.
    """
    try:
        dt = pd.to_datetime(x, errors="coerce", dayfirst=True)
        if dt is None or pd.isna(dt):
            return None
        return dt.to_pydatetime()
    except Exception:
        return None


def _make_hash(*parts) -> str:
    raw = "|".join([str(p) for p in parts])
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _excel_importrow_create(**kwargs):
    """
    Create ExcelImportRow safely even if your model columns differ.
    We only keep keys that exist as columns in ExcelImportRow.
    """
    mapper = sa_inspect(ExcelImportRow)
    cols = {c.key for c in mapper.columns}
    safe = {k: v for k, v in kwargs.items() if k in cols}
    return ExcelImportRow(**safe)


def _already_imported(factory_id: int, kind: str, row_hash: str) -> bool:
    q = db.session.query(ExcelImportRow)
    # safe filter: only if columns exist
    mapper = sa_inspect(ExcelImportRow)
    cols = {c.key for c in mapper.columns}

    if "factory_id" in cols:
        q = q.filter_by(factory_id=factory_id)
    q = q.filter_by(kind=kind, row_hash=row_hash)

    return db.session.query(q.exists()).scalar() is True


def _mark_imported(factory_id: int, kind: str, row_hash: str, filename: str = None, sheet: str = None):
    row = _excel_importrow_create(
        factory_id=factory_id,
        kind=kind,
        row_hash=row_hash,
        file_name=filename,
        sheet_name=sheet,
        imported_at=datetime.utcnow(),
    )
    db.session.add(row)


def _ensure_shop_stock(product: Product) -> ShopStock:
    """
    Your ShopStock model does NOT have factory_id.
    It’s 1:1 with Product (unique product_id).
    """
    if product.shop_stock:
        return product.shop_stock
    stock = ShopStock(product_id=product.id, quantity=0)
    db.session.add(stock)
    db.session.flush()
    return stock


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
        query = query.filter(or_(Product.name.ilike(like), Product.category.ilike(like)))

    if selected_category:
        query = query.filter(Product.category == selected_category)

    if sort == "name":
        query = query.order_by(Product.name.asc())
    elif sort == "qty_total":
        query = query.order_by((Product.quantity + func.coalesce(ShopStock.quantity, 0)).desc())
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

        rows.append({"p": product, "qty_factory": qty_factory, "qty_shop": qty_shop_val, "qty_total": qty_total})

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
#   📥 IMPORT FROM EXCEL (ALL SHEETS)
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

    filename = secure_filename(file.filename)

    data = file.read()
    bio = BytesIO(data)

    try:
        xls = pd.ExcelFile(bio)
    except Exception as e:
        flash(f"Could not read Excel file: {e}", "danger")
        return redirect(url_for("products.list_products"))

    total_models_updated = 0
    total_sales_added = 0
    total_cash_added = 0
    skipped_duplicates = 0

    try:
        for sheet in xls.sheet_names:
            # IMPORTANT: do NOT convert everything to string.
            # We read raw values so Excel dates & numbers survive.
            raw = pd.read_excel(xls, sheet_name=sheet, header=None)

            # -------------------------
            # Find "Реализация" header row:
            # Число | Модель | Сони | Нархи | Сумма
            # -------------------------
            реал_row = None
            реал_cols = None

            max_scan = min(160, len(raw))
            for r in range(max_scan):
                row_vals = [ _norm(v) for v in raw.iloc[r].tolist() ]
                row_text = " ".join(row_vals)

                has_date = ("число" in row_text) or ("дата" in row_text)
                has_model = ("модел" in row_text) or ("модель" in row_text)
                has_qty = ("сони" in row_text) or ("soni" in row_text)
                has_price = ("нархи" in row_text) or ("цена" in row_text)

                if has_date and has_model and has_qty and has_price:
                    def find_idx(keys):
                        for i, v in enumerate(row_vals):
                            if any(k in v for k in keys):
                                return i
                        return None

                    i_date = find_idx(["число", "дата"])
                    i_model = find_idx(["модел", "модель"])
                    i_qty = find_idx(["сони", "soni"])
                    i_price = find_idx(["нархи", "цена"])
                    i_sum = find_idx(["сумма"])  # optional

                    if None not in (i_date, i_model, i_qty, i_price):
                        реал_row = r
                        реал_cols = (i_date, i_model, i_qty, i_price, i_sum)
                        break

            # -------------------------
            # Find "Касса" table header row:
            # "Касса" + header contains "Число"+"Сумма" (and NOT model)
            # -------------------------
            cash_row = None
            cash_cols = None

            max_scan = min(200, len(raw))
            for r in range(max_scan):
                row_vals = [ _norm(v) for v in raw.iloc[r].tolist() ]
                row_text = " ".join(row_vals)

                if ("модел" in row_text) or ("модель" in row_text):
                    continue

                has_date = ("число" in row_text) or ("дата" in row_text)
                has_sum = ("сумма" in row_text)

                if has_date and has_sum:
                    prev = " ".join([_norm(v) for v in raw.iloc[r - 1].tolist()]) if r > 0 else ""
                    if "касса" in prev or "касса" in row_text:
                        def find_idx(keys):
                            for i, v in enumerate(row_vals):
                                if any(k in v for k in keys):
                                    return i
                            return None

                        i_date = find_idx(["число", "дата"])
                        i_sum = find_idx(["сумма"])
                        if None not in (i_date, i_sum):
                            cash_row = r
                            cash_cols = (i_date, i_sum)
                            break

            # =========================
            # Process Реализация -> update products (sell price) + create Sales + movements
            # =========================
            if реал_row is not None:
                i_date, i_model, i_qty, i_price, _i_sum = реал_cols

                current_date = None  # last valid date (for ###### rows)

                for r in range(реал_row + 1, len(raw)):
                    model_val = raw.iat[r, i_model]
                    model = ("" if model_val is None else str(model_val)).strip()
                    if not model or model.lower() == "nan":
                        continue

                    qty = _clean_int(raw.iat[r, i_qty])
                    price = _clean_int(raw.iat[r, i_price])

                    # date handling:
                    dt = _safe_excel_datetime(raw.iat[r, i_date])
                    if dt is not None:
                        current_date = dt.date()
                    else:
                        # Excel can show ###### (or blank) -> reuse last good date
                        if current_date is None:
                            current_date = date.today()

                    sold_date = current_date

                    # upsert product
                    product = Product.query.filter_by(factory_id=factory_id, name=model).first()
                    if not product:
                        product = Product(factory_id=factory_id, name=model)
                        db.session.add(product)
                        db.session.flush()

                    # update sell price from Excel if present
                    if price > 0:
                        old = float(product.sell_price_per_item or 0)
                        new = float(price)
                        if old != new:
                            product.sell_price_per_item = new
                            total_models_updated += 1

                    # import sale (dedupe)
                    # unique: factory + sheet + sold_date + model + qty + price
                    if qty > 0 and price > 0:
                        sale_hash = _make_hash("sale", factory_id, sheet, sold_date, model, qty, price)
                        if _already_imported(factory_id, "sale", sale_hash):
                            skipped_duplicates += 1
                        else:
                            # ensure shop stock exists (optional, but keeps system consistent)
                            stock = _ensure_shop_stock(product)

                            # reduce shop stock but never negative
                            available = int(stock.quantity or 0)
                            stock.quantity = max(0, available - qty)

                            sale = Sale(
                                product_id=product.id,
                                date=sold_date,
                                quantity=qty,
                                sell_price_per_item=float(price),
                                cost_price_per_item=float(product.cost_price_per_item or 0),
                                currency=product.currency or "UZS",
                                customer_name="Excel",
                                customer_phone=None,
                            )
                            db.session.add(sale)

                            db.session.add(
                                StockMovement(
                                    factory_id=factory_id,
                                    product_id=product.id,
                                    qty_change=-qty,
                                    source="shop",
                                    destination="customer",
                                    movement_type="shop_sale",
                                    comment=f"Excel import: {filename} / {sheet}",
                                )
                            )

                            _mark_imported(factory_id, "sale", sale_hash, filename=filename, sheet=sheet)
                            total_sales_added += 1

            # =========================
            # Process Касса -> CashRecord
            # =========================
            if cash_row is not None:
                i_date, i_sum = cash_cols

                current_cash_date = None

                for r in range(cash_row + 1, len(raw)):
                    raw_date = raw.iat[r, i_date]
                    raw_sum = raw.iat[r, i_sum]

                    # skip empty rows
                    if (raw_date is None or str(raw_date).strip() == "") and (raw_sum is None or str(raw_sum).strip() == ""):
                        continue

                    dt = _safe_excel_datetime(raw_date)
                    if dt is not None:
                        current_cash_date = dt.date()
                    else:
                        if current_cash_date is None:
                            continue  # can't import without any date
                    cash_date = current_cash_date

                    amount = _clean_int(raw_sum)
                    if amount <= 0:
                        continue

                    cash_hash = _make_hash("cash", factory_id, sheet, cash_date, amount)
                    if _already_imported(factory_id, "cash", cash_hash):
                        skipped_duplicates += 1
                        continue

                    db.session.add(
                        CashRecord(
                            factory_id=factory_id,
                            date=cash_date,
                            amount=float(amount),
                            currency="UZS",
                            note=f"Excel import: {filename} / {sheet}",
                        )
                    )
                    _mark_imported(factory_id, "cash", cash_hash, filename=filename, sheet=sheet)
                    total_cash_added += 1

        db.session.commit()

        flash(
            f"Excel импорт ✅ "
            f"Цены обновлены: {total_models_updated} • "
            f"Продажи добавлены: {total_sales_added} • "
            f"Касса добавлена: {total_cash_added} • "
            f"Дубликаты пропущены: {skipped_duplicates}",
            "success",
        )
        return redirect(url_for("products.list_products"))

    except Exception as e:
        db.session.rollback()
        flash(f"Excel import failed: {e}", "danger")
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
        if fabric_price_per_unit
