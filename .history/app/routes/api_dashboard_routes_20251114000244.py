from flask import Blueprint, jsonify
from datetime import date, timedelta
from sqlalchemy import func
from ..extensions import db
from ..models import Sale, Production, Product

api_dashboard_bp = Blueprint("api_dashboard", __name__)


# ---- MONTHLY SALES (last 30 days) ----
@api_dashboard_bp.route("/api/dashboard/sales_30days")
def sales_30days():
    today = date.today()
    start = today - timedelta(days=30)

    rows = (
        db.session.query(
            Sale.date,
            func.sum(Sale.quantity * Sale.sell_price_per_item)
        )
        .filter(Sale.date >= start)
        .group_by(Sale.date)
        .order_by(Sale.date)
        .all()
    )

    labels = [str(r[0]) for r in rows]
    values = [float(r[1]) for r in rows]

    return jsonify({"labels": labels, "values": values})


# ---- MONTHLY PRODUCTION ----
@api_dashboard_bp.route("/api/dashboard/production_30days")
def production_30days():
    today = date.today()
    start = today - timedelta(days=30)

    rows = (
        db.session.query(
            Production.date,
            func.sum(Production.quantity)
        )
        .filter(Production.date >= start)
        .group_by(Production.date)
        .order_by(Production.date)
        .all()
    )

    labels = [str(r[0]) for r in rows]
    values = [int(r[1]) for r in rows]

    return jsonify({"labels": labels, "values": values})


# ---- PRODUCT-WISE SALES (pie chart) ----
@api_dashboard_bp.route("/api/dashboard/product_sales")
def product_sales():
    rows = (
        db.session.query(
            Product.name,
            func.sum(Sale.quantity * Sale.sell_price_per_item)
        )
        .join(Sale, Sale.product_id == Product.id)
        .group_by(Product.id)
        .all()
    )

    labels = [r[0] for r in rows]
    values = [float(r[1]) for r in rows]

    return jsonify({"labels": labels, "values": values})
