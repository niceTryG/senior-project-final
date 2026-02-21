from datetime import date
from flask import Blueprint, render_template
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models import Product, Production

factory_bp = Blueprint("factory", __name__, url_prefix="/factory")


@factory_bp.route("/produce", methods=["GET"])
@login_required
def produce_today():
    factory_id = current_user.factory_id

    # 1) list products for this factory
    products = (
        Product.query
        .filter_by(factory_id=factory_id)
        .order_by(Product.category.asc().nullslast(), Product.name.asc())
        .all()
    )

    # 2) sum today's production by product_id
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

    # 3) build map for Jinja: {product_id: qty_today}
    today_map = {pid: int(qty or 0) for (pid, qty) in rows}
    today_total = sum(today_map.values())

    return render_template(
        "factory/produce_today.html",
        products=products,
        today_map=today_map,
        today_total=today_total,
    )