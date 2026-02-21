from flask import Blueprint, render_template
from flask_login import login_required
from ..services.product_service import ProductService

shop_report_bp = Blueprint("shop_report", __name__)
product_service = ProductService()

@shop_report_bp.route("/shop/weekly_report")
@login_required
def weekly_report():
    data = product_service.weekly_shop_report()
    return render_template("shop/weekly_report.html", **data)
