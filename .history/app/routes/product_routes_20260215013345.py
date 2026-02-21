import os
import math
from datetime import datetime, date 
from io import BytesIO
import hashlib
from ..models import CashRecord, StockMovement, ExcelImportRow
import hashlib
from ..models import CashRecord, StockMovement, ExcelImportRow


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

    # ---------- helpers ----------
    def norm(x: str) -> str:
        return str(x).strip().lower()

    def clean_int(x):
        if x is None:
            return 0
        if isinstance(x, str):
            x = x.strip().replace(" ", "").replace(",", ".")
            if not x:
                return 0
        try:
            return int(float(x))
        except Exception:
            return 0

    def make_hash(*parts) -> str:
        raw = "|".join([str(p) for p in parts])
        return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()

    def already_imported(kind: str, row_hash: str) -> bool:
        return db.session.query(ExcelImportRow.id).filter_by(
            factory_id=factory_id, kind=kind, row_hash=row_hash
        ).first() is not None

    def mark_imported(kind: str, row_hash: str):
        db.session.add(ExcelImportRow(factory_id=factory_id, kind=kind, row_hash=row_hash))

    # ---------- scan each sheet ----------
    try:
        for sheet in xls.sheet_names:
            raw = pd.read_excel(xls, sheet_name=sheet, header=None).fillna("")
            raw = raw.astype(str)

            # -------------------------
            # Find "Реализация" header row
            # expects: Число | Модел/Модель | Сони | Нархи | Сумма
            # -------------------------
            реал_row = None
            реал_cols = None

            for r in range(min(120, len(raw))):
                row_vals = [norm(v) for v in raw.iloc[r].tolist()]
                row_text = " ".join(row_vals)

                has_date = ("число" in row_text) or ("дата" in row_text)
                has_model = ("модел" in row_text) or ("модель" in row_text)
                has_qty = ("сони" in row_text) or ("soni" in row_text)
                has_price = ("нархи" in row_text) or ("цена" in row_text)
                has_sum = ("сумма" in row_text)

                if has_date and has_model and has_qty and has_price:
                    # take indexes of key columns
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
            # Find "Касса" table header row
            # Usually: row above contains "Касса", and header has "Число"+"Сумма" without "Модел"
            # -------------------------
            cash_row = None
            cash_cols = None

            for r in range(min(140, len(raw))):
                row_vals = [norm(v) for v in raw.iloc[r].tolist()]
                row_text = " ".join(row_vals)

                if ("модел" in row_text) or ("модель" in row_text):
                    continue

                has_date = ("число" in row_text) or ("дата" in row_text)
                has_sum = ("сумма" in row_text)

                if has_date and has_sum:
                    prev = " ".join([norm(v) for v in raw.iloc[r - 1].tolist()]) if r > 0 else ""
                    if "касса" in prev or "касса" in row_text:
                        # locate columns
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
            # Process Реализация -> Products + Sales + ShopStock
            # =========================
            if реал_row is not None:
                i_date, i_model, i_qty, i_price, _i_sum = реал_cols

                for r in range(реал_row + 1, len(raw)):
                    model = raw.iat[r, i_model].strip()
                    if not model or model.lower() == "nan":
                        continue

                    qty = clean_int(raw.iat[r, i_qty])
                    price = clean_int(raw.iat[r, i_price])

                    # stop if table ended (optional heuristic)
                    if model == "" and qty == 0 and price == 0:
                        continue

                    sold_date = pd.to_datetime(raw.iat[r, i_date], errors="coerce", dayfirst=True)
                    if sold_date is None or pd.isna(sold_date):
                        # in your file sometimes date cell is like "06-Oct"
                        sold_date = date.today()
                    else:
                        sold_date = sold_date.date()

                    # ----- upsert product -----
                    product = Product.query.filter_by(factory_id=factory_id, name=model).first()
                    if not product:
                        product = Product(factory_id=factory_id, name=model)
                        db.session.add(product)
                        db.session.flush()

                    # update product selling price from Excel
                    if price > 0 and (product.sell_price_per_item or 0) == 0:
                        product.sell_price_per_item = float(price)
                        total_models_updated += 1
                    elif price > 0 and float(price) != float(product.sell_price_per_item or 0):
                        # keep latest price (you can change to max() if you prefer)
                        product.sell_price_per_item = float(price)
                        total_models_updated += 1

                    # ----- sale import (dedupe) -----
                    # unique by: factory + sheet + date + model + qty + price
                    sale_hash = make_hash("sale", sheet, sold_date, model, qty, price)
                    if qty > 0 and price > 0 and not already_imported("sale", sale_hash):
                        # ensure shop stock exists
                        if not product.shop_stock:
                            product.shop_stock = ShopStock(quantity=0)
                            db.session.add(product.shop_stock)
                            db.session.flush()

                        # reduce shop stock ONLY if available, otherwise sell anyway (cash-first)
                        available = int(product.shop_stock.quantity or 0)
                        sell_qty = qty  # cash-first mode; set to min(qty, available) if strict mode
                        product.shop_stock.quantity = max(0, available - sell_qty)

                        sale = Sale(
                            product_id=product.id,
                            date=sold_date,
                            quantity=sell_qty,
                            sell_price_per_item=float(price),
                            cost_price_per_item=float(product.cost_price_per_item or 0),
                            currency=product.currency or "UZS",
                            customer_name="Excel",
                            customer_phone=None,
                        )
                        db.session.add(sale)

                        # stock movement (optional but useful)
                        db.session.add(
                            StockMovement(
                                factory_id=factory_id,
                                product_id=product.id,
                                qty_change=-sell_qty,
                                source="shop",
                                destination="customer",
                                movement_type="shop_sale",
                                comment=f"Excel import: {sheet} {sold_date}",
                            )
                        )

                        mark_imported("sale", sale_hash)
                        total_sales_added += 1

            # =========================
            # Process Касса -> CashRecord
            # =========================
            if cash_row is not None:
                i_date, i_sum = cash_cols
                for r in range(cash_row + 1, len(raw)):
                    raw_date = raw.iat[r, i_date].strip()
                    raw_sum = raw.iat[r, i_sum].strip()

                    if not raw_date and not raw_sum:
                        continue

                    dt = pd.to_datetime(raw_date, errors="coerce", dayfirst=True)
                    if dt is None or pd.isna(dt):
                        continue
                    cash_date = dt.date()

                    amount = clean_int(raw_sum)
                    if amount <= 0:
                        continue

                    cash_hash = make_hash("cash", sheet, cash_date, amount)
                    if already_imported("cash", cash_hash):
                        continue

                    db.session.add(
                        CashRecord(
                            factory_id=factory_id,
                            date=cash_date,
                            amount=float(amount),
                            currency="UZS",
                            note=f"Excel import ({sheet})",
                        )
                    )
                    mark_imported("cash", cash_hash)
                    total_cash_added += 1

        db.session.commit()
        flash(
            f"Excel импорт ✅ "
            f"Цена обновлена: {total_models_updated}, "
            f"Продажи добавлены: {total_sales_added}, "
            f"Касса добавлена: {total_cash_added}",
            "success",
        )
        return redirect(url_for("products.list_products"))

    except Exception as e:
        db.session.rollback()
        flash(f"Excel import failed: {e}", "danger")
        return redirect(url_for("products.list_products"))

def _import_dad_sales_excel(df: pd.DataFrame, factory_id: int):
    """
    Dad Excel import as PRODUCTS (qty + price), not sales.
    Columns: Число | Модел/Модель | Сони | Нархи | Сумма
    """
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    name_col = "модел" if "модел" in df.columns else ("модель" if "модель" in df.columns else None)
    qty_col = "сони" if "сони" in df.columns else ("soni" if "soni" in df.columns else None)
    price_col = "нархи" if "нархи" in df.columns else ("цена" if "цена" in df.columns else None)

    if not name_col or not qty_col:
        flash("Dad Excel: не нашёл колонки 'Модел/Модель' и 'Сони'.", "danger")
        return redirect(url_for("products.list_products"))

    # ---- clean qty/price ----
    def clean_int(x):
        if x is None:
            return 0
        if isinstance(x, str):
            x = x.strip().replace(" ", "").replace(",", ".")
            if not x:
                return 0
        try:
            # handles "60 000" -> after removing spaces, float -> int
            return int(float(x))
        except Exception:
            return 0

    # ---- aggregate per model ----
    agg = {}  # name -> {"qty": int, "price": int}
    for _, row in df.iterrows():
        name = str(row.get(name_col, "")).strip()
        if not name or name.lower() == "nan":
            continue

        qty = clean_int(row.get(qty_col, 0))
        price = clean_int(row.get(price_col, 0)) if price_col else 0

        if name not in agg:
            agg[name] = {"qty": 0, "price": 0}

        agg[name]["qty"] += max(qty, 0)

        # keep latest non-zero price
        if price > 0:
            agg[name]["price"] = price

    created = 0
    updated = 0

    try:
        for name, data in agg.items():
            qty = data["qty"]
            price = data["price"]

            product = Product.query.filter_by(factory_id=factory_id, name=name).first()
            if not product:
                product = Product(factory_id=factory_id, name=name)
                db.session.add(product)
                db.session.flush()
                created += 1
            else:
                updated += 1

            # ✅ set quantity to FACTORY stock
            if hasattr(product, "quantity"):
                product.quantity = (product.quantity or 0) + qty

            # ✅ set sell price
            if hasattr(product, "sell_price_per_item") and price > 0:
                product.sell_price_per_item = price

            # ✅ ensure currency if field exists
            if hasattr(product, "currency") and not getattr(product, "currency", None):
                product.currency = "UZS"

        db.session.commit()
        flash(f"Excel импорт ✅ создано: {created}, обновлено: {updated}", "success")
        return redirect(url_for("products.list_products"))

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
