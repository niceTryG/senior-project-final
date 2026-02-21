from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import or_, func
from datetime import datetime
from ..models import StockMovement, Product

history_bp = Blueprint("history", __name__, url_prefix="/history")

@history_bp.route("/movements", methods=["GET"])
@login_required
def movement_history():
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "newest")

    query = StockMovement.query.join(Product, StockMovement.product_id == Product.id)

    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            or_(
                func.lower(Product.name).like(like),
                func.lower(StockMovement.comment).like(like),
            )
        )

    if sort == "oldest":
        query = query.order_by(StockMovement.timestamp.asc())
    else:
        query = query.order_by(StockMovement.timestamp.desc())

    movements = query.all()

    return render_template(
        "history/movements.html",
        movements=movements,
        q=q,
        sort=sort,
    )

@history_bp.route("/order/<int:order_id>", methods=["GET"])
@login_required
def history_by_order(order_id):
    movements = (
        StockMovement.query
        .filter_by(order_id=order_id)
        .order_by(StockMovement.timestamp.desc())
        .all()
    )
    return render_template("history/movements_by_order.html", movements=movements, order_id=order_id)
