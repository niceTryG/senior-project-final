from flask import Blueprint, render_template
from flask_login import login_required, current_user   # ← IMPORTANT

from ..services.product_service import ProductService

shop_monthly_bp = Blueprint("shop_monthly", __name__, url_prefix="/shop/monthly_report")
product_service = ProductService()


@shop_monthly_bp.route("/", methods=["GET"])
@login_required
def monthly_report():
    # now current_user is defined because we imported it above
    data = product_service.get_monthly_report(factory_id=current_user.factory_id)
    return render_template("shop/monthly_report.html", **data)
