from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Product, Production


factory_bp = Blueprint("factory", __name__, url_prefix="/factory")


# =========================================================
# 🏭 PRODUCE TODAY — PAGE
# Dad goes to factory, counts models, enters quantities
# =========================================================
@factory_bp.route("/produce", methods=["GET"])
@login_required
def produce_today():
    # All products of THIS factory
    products = (
        Product.query
        .filter_by(factory_id=current_user.factory_id)
        .order_by(Product.name)
        .all()
    )

    today = date.today()

    # What was already produced today (for prefill / visibility)
    produced_today = {
        p.product_id: p.quantity
        for p in Production.query
            .filter_by(date=today)
            .join(Product)
            .filter(Product.factory_id == current_user.factory_id)
            .all()
    }

    return render_template(
        "factory/produce_today.html",
        products=products,
        produced_today=produced_today,
        today=today,
    )


# =========================================================
# 💾 SAVE TODAY PRODUCTION
# Updates stock + writes production history
# =========================================================
@factory_bp.route("/produce/save", methods=["POST"])
@login_required
def produce_today_save():
    today = date.today()

    for key, value in request.form.items():
        if not key.startswith("product_"):
            continue

        product_id = int(key.replace("product_", ""))
        qty = int(value or 0)

        if qty <= 0:
            continue

        product = Product.query.filter_by(
            id=product_id,
            factory_id=current_user.factory_id
        ).first()

        if not product:
            continue

        # Increase factory stock
        product.quantity += qty

        # Save production history
        production = Production(
            product_id=product.id,
            quantity=qty,
            date=today,
        )
        db.session.add(production)

    db.session.commit()

    return redirect(url_for("factory.produce_today"))