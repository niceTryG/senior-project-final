from flask import Blueprint, render_template
from flask_login import login_required, current_user
from ..services.product_service import ProductService

shop_report_bp = Blueprint("shop_report", __name__, url_prefix="/shop/weekly_report")
product_service = ProductService()

@shop_report_bp.route("/", methods=["GET"])
@login_required
def weekly_report():
    data = product_service.weekly_shop_report(factory_id=current_user.factory_id)
    return render_template("shop/weekly_report.html", **data)
