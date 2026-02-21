from datetime import datetime, date, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required

from ..auth_utils import roles_required
from ..models import CashRecord, Sale

cash_bp = Blueprint("cash", __name__, url_prefix="/cash")


@cash_bp.route("/")
@login_required
@roles_required("admin", "manager", "accountant")
def list_cash():
    # --- FILTER RANGE (for history table) ---
    date_from_str = request.args.get("from", "").strip()
    date_to_str = request.args.get("to", "").strip()

    date_from = None
    date_to = None
    fmt = "%Y-%m-%d"

    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, fmt).date()
        except ValueError:
            date_from = None

    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, fmt).date()
        except ValueError:
            date_to = None

    q = CashRecord.query
    if date_from:
        q = q.filter(CashRecord.date >= date_from)
    if date_to:
        q = q.filter(CashRecord.date <= date_to)

    records = (
        q.order_by(CashRecord.date.desc(), CashRecord.id.desc())
        .all()
    )

    # totals by currency for the selected period
    total_uzs = sum(r.amount for r in records if r.currency == "UZS")
    total_usd = sum(r.amount for r in records if r.currency == "USD")

    # --- WEEKLY SALES (last 7 days, only UZS) ---
    today = date.today()
    week_start = today - timedelta(days=6)

    weekly_sales = (
        Sale.query
        .filter(
            Sale.date >= week_start,
            Sale.date <= today,
            Sale.currency == "UZS",
        )
        .all()
    )

    weekly_items_sold = sum(s.quantity for s in weekly_sales)
    weekly_sales_uzs = sum(s.total_sell for s in weekly_sales)

    return render_template(
        "cash/list.html",
        records=records,
        date_from=date_from_str,
        date_to=date_to_str,
        total_uzs=total_uzs,
        total_usd=total_usd,
        weekly_items_sold=weekly_items_sold,
        weekly_sales_uzs=weekly_sales_uzs,
    )
