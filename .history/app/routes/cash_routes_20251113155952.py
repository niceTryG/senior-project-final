from flask import Blueprint, render_template, request
from flask_login import login_required
from datetime import datetime
from ..services.cash_service import CashService
from ..auth_utils import roles_required

cash_bp = Blueprint("cash", __name__, url_prefix="/cash")
service = CashService()


@cash_bp.route("/", methods=["GET"])
@login_required
@roles_required("admin", "manager")
def list_cash():
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

    records = service.list_records(date_from, date_to)
    total_uzs, total_usd = service.totals(date_from, date_to)

    return render_template(
        "cash/list.html",
        records=records,
        date_from=date_from_str,
        date_to=date_to_str,
        total_uzs=total_uzs,
        total_usd=total_usd,
    )
