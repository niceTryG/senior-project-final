from flask import Blueprint, render_template
from flask_login import login_required, current_user
from datetime import date

from ..models import Fabric, Cut
from ..extensions import db

fabric_report_bp = Blueprint("fabric_report", __name__, url_prefix="/fabric-report")


@fabric_report_bp.route("/usage")
@login_required
def usage_report():
    factory_id = current_user.factory_id

    # только ткани текущей фабрики
    fabrics = (
        Fabric.query
        .filter_by(factory_id=factory_id)
        .order_by(Fabric.name.asc())
        .all()
    )

    report = []

    for fabric in fabrics:
        # all cuts for this fabric (они уже завязаны на эту фабрику через fabric_id)
        cuts = Cut.query.filter_by(fabric_id=fabric.id).all()

        used = sum(c.used_amount for c in cuts)
        remaining = fabric.quantity
        bought = used + remaining

        price = fabric.price_per_unit or 0
        cost_used = used * price
        cost_remaining = remaining * price
        cost_total = bought * price

        efficiency = 0
        if bought > 0:
            efficiency = round((used / bought) * 100, 2)

        report.append({
            "fabric": fabric,
            "bought": bought,
            "used": used,
            "remaining": remaining,
            "cost_used": cost_used,
            "cost_remaining": cost_remaining,
            "cost_total": cost_total,
            "efficiency": efficiency,
        })

    return render_template("fabrics/usage_report.html", report=report)
