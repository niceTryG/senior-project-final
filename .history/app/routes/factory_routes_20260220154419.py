from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models import Product, Production

factory_bp = Blueprint("factory", __name__, url_prefix="/factory")


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
    )


@factory_bp.route("/produce/save", methods=["POST"])
@login_required
def produce_today_save():
    """
    Save today's production counts from the form.
    Expected form fields (example):
      qty_<product_id> = 5
    Only values > 0 are saved as Production rows.
    """
    factory_id = current_user.factory_id
    products = _get_products_for_factory(factory_id)
    allowed_ids = {p.id for p in products}

    created = 0

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
        created += 1

    if created > 0:
        db.session.commit()
        flash(f"✅ Сохранено позиций: {created}", "success")
    else:
        flash("⚠️ Ничего не сохранено (введите количество)", "warning")

    return redirect(url_for("factory.produce_today"))