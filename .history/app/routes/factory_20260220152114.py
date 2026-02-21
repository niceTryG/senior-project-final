from datetime import date
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Product, Production, StockMovement


@login_required
def produce_today():
    # security: must have factory_id
    if not current_user.factory_id:
        flash("No factory assigned.", "danger")
        return redirect(url_for("main.dashboard"))

    q = (request.args.get("q") or "").strip()
    selected_category = (request.args.get("category") or "").strip()

    # base query: only this factory
    query = Product.query.filter_by(factory_id=current_user.factory_id).order_by(Product.name.asc())

    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    if selected_category:
        query = query.filter(Product.category == selected_category)

    products = query.all()

    # categories for filter
    categories = (
        db.session.query(Product.category)
        .filter(Product.factory_id == current_user.factory_id)
        .filter(Product.category.isnot(None))
        .distinct()
        .order_by(Product.category.asc())
        .all()
    )
    categories = [c[0] for c in categories if c[0]]

    # today's production summary (for showing current totals)
    today = date.today()
    today_rows = (
        db.session.query(Production, Product)
        .join(Product, Product.id == Production.product_id)
        .filter(Product.factory_id == current_user.factory_id)
        .filter(Production.date == today)
        .all()
    )

    today_map = {p.id: prod.quantity for (prod, p) in today_rows}

    return render_template(
        "factory/produce_today.html",
        products=products,
        categories=categories,
        q=q,
        selected_category=selected_category,
        today_map=today_map,
        today=today,
    )


@login_required
def produce_today_save():
    if not current_user.factory_id:
        flash("No factory assigned.", "danger")
        return redirect(url_for("main.dashboard"))

    today = date.today()

    # We accept many inputs: qty_<product_id>
    # Example input name: qty_12 = "5"
    updates = 0

    for key, val in request.form.items():
        if not key.startswith("qty_"):
            continue

        try:
            product_id = int(key.replace("qty_", ""))
            qty = int(val or 0)
        except ValueError:
            continue

        if qty <= 0:
            continue

        # product must belong to current factory
        product = Product.query.filter_by(id=product_id, factory_id=current_user.factory_id).first()
        if not product:
            continue

        # UPSERT production row (one row per product per day)
        prod = Production.query.filter_by(product_id=product.id, date=today).first()
        if prod:
            prod.quantity += qty
        else:
            prod = Production(product_id=product.id, date=today, quantity=qty)
            db.session.add(prod)

        # update factory stock (Product.quantity is factory stock in your system)
        product.quantity = (product.quantity or 0) + qty

        # audit trail
        db.session.add(
            StockMovement(
                factory_id=current_user.factory_id,
                product_id=product.id,
                qty_change=qty,
                source="factory",
                destination="factory",
                movement_type="production",
                comment=f"Produced today by {current_user.username}",
            )
        )

        updates += 1

    if updates:
        db.session.commit()
        flash("Производство сохранено ✅", "success")
    else:
        flash("Ничего не добавлено.", "warning")

    return redirect(url_for("factory.produce_today"))