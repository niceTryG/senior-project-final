from flask import Blueprint, jsonify
from datetime import date, timedelta
from sqlalchemy import func
from ..extensions import db
from ..models import Sale, Production, Product

api_dashboard_bp = Blueprint("api_dashboard", __name__, url_prefix="/api/dashboard")

@api_dashboard_bp.route("/sales_30days", methods=["GET"])
def sales_30days():
    today = date.today()
    start = today - timedelta(days=30)

    rows = (
        db.session.query(
            Sale.date,
            func.coalesce(func.sum(Sale.quantity * Sale.sell_price_per_item), 0),
        )
        .filter(Sale.date >= start)
        .group_by(Sale.date)
        .order_by(Sale.date)
        .all()
    )

    labels = [str(r[0]) for r in rows]
    values = [int(r[1]) for r in rows]

    return jsonify({"labels": labels, "values": values})

@api_dashboard_bp.route("/production_30days", methods=["GET"])
def production_30days():
    today = date.today()
    start = today - timedelta(days=30)

    rows = (
        db.session.query(
            Production.date,
            func.coalesce(func.sum(Production.quantity), 0)
        )
        .filter(Production.date >= start)
        .group_by(Production.date)
        .order_by(Production.date)
        .all()
    )

    labels = [str(r[0]) for r in rows]
    values = [int(r[1]) for r in rows]

    return jsonify({"labels": labels, "values": values})

@api_dashboard_bp.route("/product_sales", methods=["GET"])
def product_sales():
    rows = (
        db.session.query(
            Product.name,
            func.coalesce(func.sum(Sale.quantity * Sale.sell_price_per_item), 0)
        )
        .join(Sale, Sale.product_id == Product.id)
        .group_by(Product.id)
        .all()
    )

    labels = [r[0] for r in rows]
    values = [int(r[1]) for r in rows]

    return jsonify({"labels": labels, "values": values})
