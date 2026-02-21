from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models import Product, Production, Movement
from app.services.shop_service import ShopService
from sqlalchemy import func, or_


def _norm(s: str) -> str:
    return (s or "").strip().lower()


# super practical RU/UZ-ish translit helpers (not perfect, but works well for names)
_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "қ": "q", "ў": "o", "ғ": "g", "ҳ": "h",  # uz cyr extras
}

_LAT_TO_CYR = {
    # very rough, but helps
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "e": "е",
    "j": "ж", "z": "з", "i": "и", "y": "й", "k": "к", "l": "л",
    "m": "м", "n": "н", "o": "о", "p": "п", "r": "р", "s": "с",
    "t": "т", "u": "у", "f": "ф", "h": "х", "q": "қ",
}

def _to_lat(s: str) -> str:
    s = _norm(s)
    out = []
    for ch in s:
        out.append(_CYR_TO_LAT.get(ch, ch))
    return "".join(out)

def _to_cyr(s: str) -> str:
    s = _norm(s)
    # handle common digraphs first
    s = (s.replace("sh", "ш")
           .replace("ch", "ч")
           .replace("yo", "ё")
           .replace("yu", "ю")
           .replace("ya", "я")
           .replace("ts", "ц"))
    out = []
    for ch in s:
        out.append(_LAT_TO_CYR.get(ch, ch))
    return "".join(out)

def _q_variants(q: str) -> list[str]:
    q0 = _norm(q)
    if not q0:
        return []
    v = {q0}
    v.add(_to_lat(q0))
    v.add(_to_cyr(q0))
    # also remove spaces/dashes to catch “ad i das”
    v.add(q0.replace(" ", "").replace("-", ""))
    return [x for x in v if x]
factory_bp = Blueprint("factory", __name__, url_prefix="/factory")
shop_service = ShopService()


def _get_categories_for_factory(factory_id: int):
    rows = (
        db.session.query(Product.category)
        .filter(Product.factory_id == factory_id)
        .filter(Product.category.isnot(None))
        .filter(func.trim(Product.category) != "")
        .distinct()
        .order_by(Product.category.asc())
        .all()
    )
    return [r[0] for r in rows if r and r[0]]


def _get_products_for_factory_filtered(factory_id: int, q: str | None, category: str | None):
    query = Product.query.filter(Product.factory_id == factory_id)

    if category:
        query = query.filter(Product.category == category)

    if q:
        variants = _q_variants(q)
        conds = []
        for v in variants:
            conds.append(func.lower(Product.name).ilike(f"%{v}%"))
        query = query.filter(or_(*conds))

    return query.order_by(Product.category.asc().nullslast(), Product.name.asc()).all()

def _build_today_map(factory_id: int):
    rows = (
        db.session.query(
            Production.product_id,
            func.coalesce(func.sum(Production.quantity), 0).label("qty"),
        )
        .join(Product, Product.id == Production.product_id)
        .filter(Product.factory_id == factory_id)
        .filter(Production.date == date.today())
        .group_by(Production.product_id)
        .all()
    )
    today_map = {pid: int(qty or 0) for (pid, qty) in rows}
    today_total = sum(today_map.values())
    return today_map, today_total


@factory_bp.route("/produce", methods=["GET"])
@login_required
def produce_today():
    factory_id = current_user.factory_id

    # ✅ read filters from query string
    q = (request.args.get("q") or "").strip()
    selected_category = (request.args.get("category") or "").strip()

    # ✅ dropdown categories (for this factory)
    categories = _get_categories_for_factory(factory_id)

    # ✅ filtered products list
    products = _get_products_for_factory_filtered(
        factory_id=factory_id,
        q=q or None,
        category=selected_category or None,
    )

    today_map, today_total = _build_today_map(factory_id)

    return render_template(
        "factory/produce_today.html",
        products=products,
        today_map=today_map,
        today_total=today_total,
        today=date.today().strftime("%d.%m.%Y"),
        # ✅ pass filter vars (template already uses them)
        q=q,
        categories=categories,
        selected_category=selected_category,
    )


@factory_bp.route("/produce/save", methods=["POST"])
@login_required
def produce_today_save():
    """
    Save today's production counts from the form.
    Expected fields: qty_<product_id> = 5
    Saves only values > 0 as Production rows.
    Then asks: Transfer to shop now?
    """
    factory_id = current_user.factory_id

    # IMPORTANT:
    # On save, we must validate against ALL factory products (not just filtered page),
    # otherwise if user filtered, some ids might not be in the visible list.
    products = (
        Product.query
        .filter(Product.factory_id == factory_id)
        .with_entities(Product.id)
        .all()
    )
    allowed_ids = {pid for (pid,) in products}

    created_rows = 0
    saved_map = {}  # product_id -> qty_added

    for key, val in request.form.items():
        if not key.startswith("qty_"):
            continue

        try:
            product_id = int(key.replace("qty_", "").strip())
        except ValueError:
            continue

        if product_id not in allowed_ids:
            continue

        try:
            qty = int(val or 0)
        except ValueError:
            qty = 0

        if qty <= 0:
            continue

        db.session.add(
            Production(
                product_id=product_id,
                date=date.today(),
                quantity=qty,
                note="manual count",
            )
        )
        created_rows += 1
        saved_map[product_id] = saved_map.get(product_id, 0) + qty

    if created_rows <= 0:
        flash("⚠️ Ничего не сохранено (введите количество)", "warning")
        return redirect(url_for("factory.produce_today"))

    db.session.commit()

    # Store “what was just added” in session so we can show confirm screen
    session["mm_last_production_map"] = {str(k): int(v) for k, v in saved_map.items()}
    session["mm_last_production_date"] = date.today().isoformat()

    flash(f"✅ Сохранено позиций: {created_rows}", "success")
    return redirect(url_for("factory.produce_transfer_confirm"))


@factory_bp.route("/produce/transfer-confirm", methods=["GET"])
@login_required
def produce_transfer_confirm():
    """
    Confirmation screen:
    'Production saved. Transfer these items to shop now?'
    """
    factory_id = current_user.factory_id

    prod_date = session.get("mm_last_production_date")
    mp = session.get("mm_last_production_map") or {}

    # Safety: only allow confirm for today (avoid old session weirdness)
    if not prod_date or prod_date != date.today().isoformat() or not mp:
        flash("ℹ️ Нет свежего списка производства для передачи.", "info")
        return redirect(url_for("factory.produce_today"))

    # Build rows for template
    ids = []
    for k in mp.keys():
        try:
            ids.append(int(k))
        except ValueError:
            pass

    products = (
        Product.query
        .filter(Product.factory_id == factory_id, Product.id.in_(ids))
        .all()
    )
    prod_by_id = {p.id: p for p in products}

    rows = []
    total = 0
    for k, qty in mp.items():
        try:
            pid = int(k)
        except ValueError:
            continue
        p = prod_by_id.get(pid)
        if not p:
            continue
        q = int(qty or 0)
        if q <= 0:
            continue
        rows.append({"product": p, "qty": q})
        total += q

    if not rows:
        flash("ℹ️ Нет товаров для передачи.", "info")
        return redirect(url_for("factory.produce_today"))

    return render_template(
        "factory/produce_transfer_confirm.html",
        rows=rows,
        total_qty=total,
        today=date.today().strftime("%d.%m.%Y"),
    )


@factory_bp.route("/produce/transfer-now", methods=["POST"])
@login_required
def produce_transfer_now():
    """
    Transfers “last saved production list” to shop in one click.
    """
    factory_id = current_user.factory_id

    prod_date = session.get("mm_last_production_date")
    mp = session.get("mm_last_production_map") or {}

    if not prod_date or prod_date != date.today().isoformat() or not mp:
        flash("⚠️ Нет списка для передачи. Сначала сохраните производство.", "warning")
        return redirect(url_for("factory.produce_today"))

    transferred = 0
    errors = 0

    for k, qty in mp.items():
        try:
            product_id = int(k)
            quantity = int(qty or 0)
        except ValueError:
            continue

        if quantity <= 0:
            continue

        product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
        if not product:
            errors += 1
            continue

        try:
            shop_service.transfer_to_shop(
                factory_id=factory_id,
                product_id=product.id,
                quantity=quantity,
                sell_price_per_item=None,  # keep shop price unchanged
            )

            mv = Movement(
                factory_id=factory_id,
                product_id=product.id,
                source="factory",
                destination="shop",
                change=quantity,
                note=f"Авто-передача после производства: {quantity} шт.",
                created_by_id=current_user.id,
                timestamp=datetime.utcnow(),
            )
            db.session.add(mv)

            transferred += 1
        except Exception:
            errors += 1

    db.session.commit()

    session.pop("mm_last_production_map", None)
    session.pop("mm_last_production_date", None)

    if transferred > 0 and errors == 0:
        flash(f"✅ Передано в магазин позиций: {transferred}", "success")
    elif transferred > 0:
        flash(f"✅ Передано: {transferred}. ⚠️ Ошибки: {errors}.", "warning")
    else:
        flash("⚠️ Ничего не передано. Проверьте остатки и товары.", "danger")

    return redirect(url_for("shop.list_shop"))


@factory_bp.route("/produce/transfer-skip", methods=["POST"])
@login_required
def produce_transfer_skip():
    session.pop("mm_last_production_map", None)
    session.pop("mm_last_production_date", None)
    flash("Ок 👍 Передачу можно сделать позже через 'Передать в магазин'.", "info")
    return redirect(url_for("factory.produce_today"))

@factory_bp.route("/api/product-suggest")
@login_required
def product_suggest():
    factory_id = current_user.factory_id
    q = (request.args.get("q") or "").strip()
    if not q:
        return {"items": []}

    variants = _q_variants(q)
    conds = [func.lower(Product.name).ilike(f"%{v}%") for v in variants]

    items = (
        Product.query
        .filter(Product.factory_id == factory_id)
        .filter(or_(*conds))
        .order_by(Product.name.asc())
        .limit(8)
        .all()
    )

    return {"items": [{"id": p.id, "name": p.name, "category": p.category or ""} for p in items]}