# ==== app/routes/product_routes.py (REPLACE FULL FILE) ====
from flask import render_template
from ..models import Product

import os
import json
import hashlib
from io import BytesIO
from datetime import datetime, date

import pandas as pd
from werkzeug.utils import secure_filename
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    send_file,
)
from flask_login import login_required, current_user
from sqlalchemy import func, or_

from ..extensions import db
from ..auth_utils import roles_required
from ..models import (
    Product,
    ShopStock,
    Sale,
    CashRecord,
    StockMovement,
    ExcelImportRow,
    ExcelImportBatch,
)
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


from flask import session

def _ensure_factory_bound():
    """
    Returns the factory_id that actions should apply to.

    - Normal users (admin/manager) must have current_user.factory_id set.
    - Superadmin may have factory_id = None, so they must select a factory via session.
    - If no factory is selected yet, we auto-select the first one (or create a default for admin).
    """
    # 1) If user is already bound to a factory, use it
    user_factory_id = getattr(current_user, "factory_id", None)
    if user_factory_id is not None:
        return user_factory_id

    # 2) Superadmin without a bound factory: use session selection
    if getattr(current_user, "is_superadmin", False):
        selected = session.get("factory_id")
        if selected is not None:
            return selected

        # Auto-select first factory if it exists
        first = Factory.query.first()
        if first:
            session["factory_id"] = first.id
            return first.id

        # No factories exist: create one (superadmin/admin only)
        default_factory = Factory(name="Mini Moda Factory")
        db.session.add(default_factory)
        db.session.commit()
        session["factory_id"] = default_factory.id
        return default_factory.id

    # 3) Non-superadmin with no factory: block
    flash("У пользователя не привязан цех (factory). Обратитесь к администратору.", "danger")
    return None


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _import_folder(factory_id: int) -> tuple[str, str]:
    # relative (for DB)
    rel_dir = os.path.join("uploads", "excel_imports", str(factory_id))

    # absolute (on disk)
    abs_dir = os.path.join(current_app.static_folder, rel_dir)

    os.makedirs(abs_dir, exist_ok=True)
    return rel_dir, abs_dir

def _norm(s) -> str:
    return str(s).strip().lower()


def _clean_int(x) -> int:
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


def _make_hash(*parts) -> str:
    raw = "|".join([str(p) for p in parts])
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _already_imported(factory_id: int, kind: str, row_hash: str) -> bool:
    return db.session.query(ExcelImportRow.id).filter_by(
        factory_id=factory_id, kind=kind, row_hash=row_hash
    ).first() is not None


def _mark_imported(factory_id: int, kind: str, row_hash: str) -> None:
    db.session.add(ExcelImportRow(factory_id=factory_id, kind=kind, row_hash=row_hash))


def _ensure_shop_stock(product: Product) -> ShopStock:
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

    file = request.files.get("image")
    image_path = None
    if file and file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext in {"png", "jpg", "jpeg", "webp"}:
            filename = secure_filename(file.filename)
            upload_dir = current_app.config.get("UPLOAD_FOLDER", os.path.join("app", "static", "uploads", "products"))
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


# =========================================================
#   📥 EXCEL IMPORT WIZARD
# =========================================================

@products_bp.route("/import", methods=["GET"])
@login_required
@roles_required("admin", "manager")
def import_wizard():
    factory_id = _ensure_factory_bound()
    if factory_id is None:
        flash("Сначала привяжите пользователя к фабрике (factory).", "danger")
        return redirect(url_for("products.list_products"))

    batches = (
        ExcelImportBatch.query
        .filter_by(factory_id=factory_id)
        .order_by(ExcelImportBatch.uploaded_at.desc())
        .limit(20)
        .all()
    )
    return render_template("products/import_wizard.html", batches=batches)


@products_bp.route("/import/upload", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def import_upload():
    factory_id = _ensure_factory_bound()
    if factory_id is None:
        flash("Factory is not selected.", "danger")
        return redirect(url_for("products.list_products"))

    file = request.files.get("file")
    if not file or file.filename == "":
        flash("No file selected for import.", "danger")
        return redirect(url_for("products.import_wizard"))

    raw_bytes = file.read()
    if not raw_bytes:
        flash("Пустой файл.", "danger")
        return redirect(url_for("products.import_wizard"))

    filename = secure_filename(file.filename)
    file_hash = _sha256_bytes(raw_bytes)

    existing = ExcelImportBatch.query.filter_by(factory_id=factory_id, file_hash=file_hash).first()
    if existing:
        flash("Этот Excel уже был загружен раньше. Открыл существующий импорт.", "info")
        return redirect(url_for("products.import_batch_detail", batch_id=existing.id))

    # ✅ FIX: save inside /static/uploads/... and store RELATIVE path in DB
    rel_dir, abs_dir = _import_folder(factory_id)  # must return (rel_dir, abs_dir)

    stamped = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    stored_name = f"{stamped}__{filename}"

    abs_path = os.path.join(abs_dir, stored_name)
    with open(abs_path, "wb") as f:
        f.write(raw_bytes)

    rel_path = os.path.join(rel_dir, stored_name).replace("\\", "/")

    batch = ExcelImportBatch(
        factory_id=factory_id,
        filename=filename,
        stored_path=rel_path,  # ✅ RELATIVE path only!
        file_hash=file_hash,
        uploaded_by_id=current_user.id,
        status="uploaded",
    )
    db.session.add(batch)
    db.session.commit()

    bio = BytesIO(raw_bytes)
    try:
        xls = pd.ExcelFile(bio)
    except Exception as e:
        batch.status = "failed"
        batch.error = str(e)
        db.session.commit()
        flash(f"Could not read Excel file: {e}", "danger")
        return redirect(url_for("products.import_wizard"))

    sheet_info = []
    for sheet in xls.sheet_names:
        try:
            preview = pd.read_excel(xls, sheet_name=sheet, header=None, nrows=60)
        except Exception:
            preview = pd.DataFrame()

        tags = []
        if not preview.empty:
            text = " ".join(_norm(v) for v in preview.fillna("").astype(str).values.flatten().tolist())
            if ("модел" in text or "модель" in text) and ("сони" in text or "soni" in text) and ("нархи" in text or "цена" in text):
                tags.append("реализация")
            if "касса" in text and ("сумма" in text) and (("число" in text) or ("дата" in text)):
                tags.append("касса")

        sheet_info.append({"name": sheet, "tags": tags})

    return render_template("products/import_choose_sheets.html", batch=batch, sheet_info=sheet_info)
 
@products_bp.route("/import/confirm", methods=["POST"])
@login_required
@roles_required("admin", "manager")
def import_confirm():
    factory_id = _ensure_factory_bound()
    if factory_id is None:
        flash("Factory is not selected.", "danger")
        return redirect(url_for("products.import_wizard"))

    batch_id = _to_int(request.form.get("batch_id"), 0)
    batch = ExcelImportBatch.query.filter_by(id=batch_id, factory_id=factory_id).first()
    if not batch:
        flash("Import batch not found.", "danger")
        return redirect(url_for("products.import_wizard"))

    selected_sheets = request.form.getlist("sheets")
    if not selected_sheets:
        flash("Выберите хотя бы один лист.", "warning")
        return redirect(url_for("products.import_batch_detail", batch_id=batch.id))

    do_sales = request.form.get("do_sales") == "1"
    do_cash = request.form.get("do_cash") == "1"
    update_prices = request.form.get("update_prices") == "1"

    if not (do_sales or do_cash or update_prices):
        flash("Выберите что импортировать (реализация/касса/цены).", "warning")
        return redirect(url_for("products.import_batch_detail", batch_id=batch.id))

    try:
        with open(batch.stored_path, "rb") as f:
            raw_bytes = f.read()
    except Exception as e:
        flash(f"Не могу открыть файл на сервере: {e}", "danger")
        return redirect(url_for("products.import_wizard"))

    bio = BytesIO(raw_bytes)
    try:
        xls = pd.ExcelFile(bio)
    except Exception as e:
        batch.status = "failed"
        batch.error = str(e)
        db.session.commit()
        flash(f"Could not read Excel file: {e}", "danger")
        return redirect(url_for("products.import_wizard"))

    stats = {
        "prices_updated": 0,
        "products_created": 0,
        "sales_added": 0,
        "cash_added": 0,
        "warnings": [],
        "sheets": selected_sheets,
    }

    try:
        for sheet in selected_sheets:
            if sheet not in xls.sheet_names:
                stats["warnings"].append(f"Sheet not found: {sheet}")
                continue

            raw = pd.read_excel(xls, sheet_name=sheet, header=None)

            if do_sales or update_prices:
                s1 = _import_sheet_realization(
                    raw=raw,
                    factory_id=factory_id,
                    sheet_name=sheet,
                    do_sales=do_sales,
                    update_prices=update_prices,
                )
                for k in ("prices_updated", "products_created", "sales_added"):
                    stats[k] += s1.get(k, 0)
                stats["warnings"].extend(s1.get("warnings", []))

            if do_cash:
                s2 = _import_sheet_cash(raw=raw, factory_id=factory_id, sheet_name=sheet)
                stats["cash_added"] += s2.get("cash_added", 0)
                stats["warnings"].extend(s2.get("warnings", []))

        batch.status = "imported"
        batch.imported_at = datetime.utcnow()
        batch.sheets_selected = json.dumps(selected_sheets, ensure_ascii=False)
        batch.stats_json = json.dumps(stats, ensure_ascii=False)
        batch.error = None

        db.session.commit()

        flash(
            f"Excel импорт ✅ Цены: {stats['prices_updated']}, "
            f"Продажи: {stats['sales_added']}, Касса: {stats['cash_added']}",
            "success",
        )
        return redirect(url_for("products.import_batch_detail", batch_id=batch.id))

    except Exception as e:
        db.session.rollback()
        batch.status = "failed"
        batch.error = str(e)
        batch.stats_json = json.dumps(stats, ensure_ascii=False)
        db.session.commit()
        flash(f"Excel import failed: {e}", "danger")
        return redirect(url_for("products.import_batch_detail", batch_id=batch.id))


@products_bp.route("/imports/<int:batch_id>")
@login_required
@roles_required("admin", "manager")
def import_batch_detail(batch_id: int):
    factory_id = _ensure_factory_bound()
    if factory_id is None:
        return redirect(url_for("products.import_wizard"))

    batch = ExcelImportBatch.query.filter_by(id=batch_id, factory_id=factory_id).first_or_404()

    stats = {}
    if batch.stats_json:
        try:
            stats = json.loads(batch.stats_json)
        except Exception:
            stats = {}

    sheets = []
    if batch.sheets_selected:
        try:
            sheets = json.loads(batch.sheets_selected)
        except Exception:
            sheets = []

    return render_template("products/import_detail.html", batch=batch, stats=stats, sheets=sheets)


from flask import abort
import os

@products_bp.route("/imports/<int:batch_id>/download")
@login_required
@roles_required("admin", "manager")
def import_batch_download(batch_id):
    batch = ExcelImportBatch.query.get_or_404(batch_id)

    stored = batch.stored_path or ""
    stored = stored.replace("/", os.sep).replace("\\", os.sep)

    # ✅ if stored_path is relative, make it absolute from project root
    if not os.path.isabs(stored):
        stored = os.path.join(current_app.root_path, stored)

    if not os.path.exists(stored):
        flash(f"File not found on disk: {stored}", "danger")
        return redirect(url_for("products.import_wizard"))

    return send_file(stored, as_attachment=True, download_name=batch.filename)

# =========================================================
#   INTERNAL: sheet parsers
# =========================================================

def _locate_cols(row_strs, keys_map):
    out = {}
    for key, needles in keys_map.items():
        idx = None
        for i, v in enumerate(row_strs):
            if any(n in v for n in needles):
                idx = i
                break
        out[key] = idx
    return out


def _import_sheet_realization(raw: pd.DataFrame, factory_id: int, sheet_name: str, do_sales: bool, update_prices: bool):
    res = {"prices_updated": 0, "products_created": 0, "sales_added": 0, "warnings": []}

    header_row = None
    header_strs = None

    max_scan = min(180, len(raw))
    for r in range(max_scan):
        row_vals = raw.iloc[r].tolist()
        row_strs = [_norm(v) for v in row_vals]
        blob = " ".join(row_strs)

        has_date = ("число" in blob) or ("дата" in blob)
        has_model = ("модел" in blob) or ("модель" in blob)
        has_qty = ("сони" in blob) or ("soni" in blob)
        has_price = ("нархи" in blob) or ("цена" in blob)

        if has_date and has_model and has_qty and has_price:
            header_row = r
            header_strs = row_strs
            break

    if header_row is None:
        return res

    cols = _locate_cols(header_strs, {
        "date": ["число", "дата"],
        "model": ["модел", "модель"],
        "qty": ["сони", "soni"],
        "price": ["нархи", "цена"],
        "sum": ["сумма"],
    })
    if cols["date"] is None or cols["model"] is None or cols["qty"] is None or cols["price"] is None:
        res["warnings"].append(f"{sheet_name}: не смог определить колонки Реализация")
        return res

    last_valid_date = None

    for r in range(header_row + 1, len(raw)):
        model = raw.iat[r, cols["model"]] if cols["model"] < raw.shape[1] else None
        model = str(model).strip()

        if not model or model.lower() in ("nan", "none"):
            continue

        qty = _clean_int(raw.iat[r, cols["qty"]]) if cols["qty"] < raw.shape[1] else 0
        price = _clean_int(raw.iat[r, cols["price"]]) if cols["price"] < raw.shape[1] else 0

        # IMPORTANT:
        # If you want "models + price" even with empty qty -> allow price-only rows.
        if qty <= 0 and price <= 0:
            continue

        raw_date = raw.iat[r, cols["date"]] if cols["date"] < raw.shape[1] else None
        dt = pd.to_datetime(raw_date, errors="coerce", dayfirst=True)

        if dt is None or pd.isna(dt):
            sold_date = last_valid_date or date.today()
        else:
            sold_date = dt.date()
            last_valid_date = sold_date

        product = Product.query.filter_by(factory_id=factory_id, name=model).first()
        if not product:
            product = Product(factory_id=factory_id, name=model)
            db.session.add(product)
            db.session.flush()
            res["products_created"] += 1

        if update_prices and price > 0:
            current_price = float(product.sell_price_per_item or 0)
            if float(price) != current_price:
                product.sell_price_per_item = float(price)
                res["prices_updated"] += 1

        if do_sales and qty > 0 and price > 0:
            sale_hash = _make_hash("sale", sheet_name, sold_date.isoformat(), model, qty, price)
            if _already_imported(factory_id, "sale", sale_hash):
                continue

            stock = _ensure_shop_stock(product)
            available = int(stock.quantity or 0)
            stock.quantity = max(0, available - qty)

            sale = Sale(
                product_id=product.id,
                date=sold_date,
                quantity=qty,
                sell_price_per_item=float(price),
                cost_price_per_item=float(product.cost_price_per_item or 0),
                currency=product.currency or "UZS",
                customer_name="Excel import",
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
                    comment=f"Excel import: {sheet_name} {sold_date.isoformat()}",
                )
            )

            _mark_imported(factory_id, "sale", sale_hash)
            res["sales_added"] += 1

    return res


def _import_sheet_cash(raw: pd.DataFrame, factory_id: int, sheet_name: str):
    res = {"cash_added": 0, "warnings": []}

    cash_header_row = None
    header_strs = None

    max_scan = min(220, len(raw))
    for r in range(max_scan):
        row_vals = raw.iloc[r].tolist()
        row_strs = [_norm(v) for v in row_vals]
        blob = " ".join(row_strs)

        if ("модел" in blob) or ("модель" in blob):
            continue

        has_date = ("число" in blob) or ("дата" in blob)
        has_sum = ("сумма" in blob)

        if has_date and has_sum:
            prev = " ".join([_norm(v) for v in raw.iloc[r - 1].tolist()]) if r > 0 else ""
            if ("касса" in prev) or ("касса" in blob):
                cash_header_row = r
                header_strs = row_strs
                break

    if cash_header_row is None:
        return res

    cols = _locate_cols(header_strs, {"date": ["число", "дата"], "sum": ["сумма"]})
    if cols["date"] is None or cols["sum"] is None:
        res["warnings"].append(f"{sheet_name}: не смог определить колонки Касса")
        return res

    last_valid_date = None

    for r in range(cash_header_row + 1, len(raw)):
        raw_date = raw.iat[r, cols["date"]] if cols["date"] < raw.shape[1] else None
        raw_sum = raw.iat[r, cols["sum"]] if cols["sum"] < raw.shape[1] else None

        if (raw_date is None or str(raw_date).strip() == "") and (raw_sum is None or str(raw_sum).strip() == ""):
            continue

        dt = pd.to_datetime(raw_date, errors="coerce", dayfirst=True)
        if dt is None or pd.isna(dt):
            if last_valid_date is None:
                continue
            cash_date = last_valid_date
        else:
            cash_date = dt.date()
            last_valid_date = cash_date

        amount = _clean_int(raw_sum)
        if amount <= 0:
            continue

        cash_hash = _make_hash("cash", sheet_name, cash_date.isoformat(), amount)
        if _already_imported(factory_id, "cash", cash_hash):
            continue

        db.session.add(
            CashRecord(
                factory_id=factory_id,
                date=cash_date,
                amount=float(amount),
                currency="UZS",
                note=f"Excel import ({sheet_name})",
            )
        )
        _mark_imported(factory_id, "cash", cash_hash)
        res["cash_added"] += 1

    return res
# ==========================
#   💸 COST CALCULATION
# ==========================
@products_bp.route("/<int:product_id>/cost", methods=["GET", "POST"])
@login_required
def product_cost(product_id: int):
    """
    Страница расчёта себестоимости для модели.
    """
    product = Product.query.get_or_404(product_id)

    cost_data = {}

    if request.method == "POST":
        def f(name: str, default: float = 0.0) -> float:
            raw = (request.form.get(name, "") or "").strip().replace(",", ".")
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
@products_bp.route("/factory-stock", endpoint="factory_stock")
@login_required
def factory_stock():
    # temporary redirect so dashboard doesn't crash
    return redirect(url_for("products.list_products"))
