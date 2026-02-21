from flask import Blueprint, render_template
from flask_login import login_required
from datetime import date
from ..models import Fabric, Cut
from ..extensions import db

fabric_report_bp = Blueprint("fabric_report", __name__, url_prefix="/fabric-report")


@fabric_report_bp.route("/usage")
@login_required
def usage_report():
    fabrics = Fabric.query.all()
    
    report = []

    for fabric in fabrics:
        # all cuts for this fabric
        cuts = Cut.query.filter_by(fabric_id=fabric.id).all()

        used = sum(c.used_amount for c in cuts)
        remaining = fabric.quantity
        bought = used + remaining

        # cost calculations
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

    return render_template("fabric/usage_report.html", report=report)
