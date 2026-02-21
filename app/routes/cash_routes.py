from datetime import datetime, date, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from ..auth_utils import roles_required
from ..models import CashRecord, Sale, Product

cash_bp = Blueprint("cash", __name__, url_prefix="/cash")


@cash_bp.route("/")
@login_required
@roles_required("admin", "manager", "accountant")
def list_cash():
    factory_id = current_user.factory_id

    # ----- FILTER RANGE FOR HISTORY TABLE -----
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

    q = CashRecord.query.filter(CashRecord.factory_id == factory_id)
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

    # ----- LAST 7 DAYS WINDOW -----
    today = date.today()
    week_start = today - timedelta(days=6)

    # Weekly SALES (only UZS) – only for this factory
    weekly_sales = (
        Sale.query
        .join(Product)
        .filter(
            Product.factory_id == factory_id,
            Sale.date >= week_start,
            Sale.date <= today,
            Sale.currency == "UZS",
        )
        .all()
    )
    weekly_items_sold = sum(s.quantity for s in weekly_sales)
    weekly_sales_uzs = sum(s.total_sell for s in weekly_sales)

    # Weekly CASH (only UZS, +/-) – this factory only
    weekly_cash_records = (
        CashRecord.query
        .filter(
            CashRecord.factory_id == factory_id,
            CashRecord.date >= week_start,
            CashRecord.date <= today,
            CashRecord.currency == "UZS",
        )
        .all()
    )

    weekly_cash_in_uzs = sum(
        r.amount for r in weekly_cash_records if r.amount > 0
    )
    weekly_cash_out_uzs = -sum(
        r.amount for r in weekly_cash_records if r.amount < 0
    )
    weekly_cash_net_uzs = weekly_cash_in_uzs - weekly_cash_out_uzs

    return render_template(
        "cash/list.html",
        # history
        records=records,
        date_from=date_from_str,
        date_to=date_to_str,
        total_uzs=total_uzs,
        total_usd=total_usd,
        # weekly stats
        weekly_items_sold=weekly_items_sold,
        weekly_sales_uzs=weekly_sales_uzs,
        weekly_cash_in_uzs=weekly_cash_in_uzs,
        weekly_cash_out_uzs=weekly_cash_out_uzs,
        weekly_cash_net_uzs=weekly_cash_net_uzs,
    )
