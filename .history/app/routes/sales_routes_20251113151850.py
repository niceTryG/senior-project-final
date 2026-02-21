from flask import Blueprint, render_template, request
from flask_login import login_required
from datetime import datetime
from ..services.product_service import ProductService

sales_bp = Blueprint("sales", __name__, url_prefix="/sales")
service = ProductService()


@sales_bp.route("/", methods=["GET"])
@login_required
def list_sales():
    date_from_str = request.args.get("from", "").strip()
    date_to_str = request.args.get("to", "").strip()

    date_from = None
    date_to = None

    date_format = "%Y-%m-%d"

    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, date_format).date()
        except ValueError:
            date_from = None

    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, date_format).date()
        except ValueError:
            date_to = None

    sales = service.list_sales(date_from, date_to)

    return render_template(
        "sales/list.html",
        sales=sales,
        date_from=date_from_str,
        date_to=date_to_str,
    )
