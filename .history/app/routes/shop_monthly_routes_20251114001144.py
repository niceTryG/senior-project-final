from flask import Blueprint, render_template
from flask_login import login_required

from ..services.product_service import ProductService

shop_monthly_bp = Blueprint("shop_monthly", __name__)
product_service = ProductService()

@shop_monthly_bp.route("/shop/monthly_report")
@login_required
def monthly_report():
    data = product_service.get_monthly_report()
    return render_template("shop/monthly_report.html", **data)
