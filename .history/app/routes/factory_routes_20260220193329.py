from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models import Product, Production, Movement
from app.services.shop_service import ShopService

factory_bp = Blueprint("factory", __name__, url_prefix="/factory")
shop_service = ShopService()


def _get_products_for_factory(factory_id: int):
    return (
        Product.query
        .filter_by(factory_id=factory_id)
        .order_by(Product.category.asc().nullslast(), Product.name.asc())
        .all()
    )


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
    products = _get_products_for_factory(factory_id)
    today_map, today_total = _build_today_map(factory_id)

    return render_template(
        "factory/produce_today.html",
        products=products,
        today_map=today_map,
        today_total=today_total,
        today=date.today().strftime("%d.%m.%Y"),
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
    products = _get_products_for_factory(factory_id)
    allowed_ids = {p.id for p in products}

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

    # If somehow empty after filtering
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

    # Transfer each item
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
            # Business logic
            shop_service.transfer_to_shop(
                factory_id=factory_id,
                product_id=product.id,
                quantity=quantity,
                sell_price_per_item=None,  # keep shop price unchanged
            )

            # Legacy movement log (same style as shop_routes)
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
            # do not crash whole batch
            errors += 1

    db.session.commit()

    # Clear the session payload
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
    """
    User chooses 'Later' -> clear session and go back to production screen.
    """
    session.pop("mm_last_production_map", None)
    session.pop("mm_last_production_date", None)
    flash("Ок 👍 Передачу можно сделать позже через 'Передать в магазин'.", "info")
    return redirect(url_for("factory.produce_today"))