from datetime import datetime, date
from flask import Blueprint, render_template, request
from flask_login import login_required

from ..services.fabric_service import FabricService
from ..services.product_service import ProductService

accountant_report_bp = Blueprint(
    "accountant_report",
    __name__,
    url_prefix="/accountant",
)

fabric_service = FabricService()
product_service = ProductService()


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


@accountant_report_bp.route("/report")
@login_required
def report():
    # читаем даты из query-параметров
    from_str = request.args.get("from")
    to_str = request.args.get("to")

    date_from = _parse_date(from_str)
    date_to = _parse_date(to_str)

    # если ничего не указано – по умолчанию текущий месяц
    if not date_from and not date_to:
        today = date.today()
        date_from = date(today.year, today.month, 1)
        date_to = today

    usage = fabric_service.get_usage_summary(date_from=date_from, date_to=date_to)
    prod = product_service.production_summary(date_from=date_from, date_to=date_to)

    return render_template(
        "accountant/report.html",
        date_from=date_from,
        date_to=date_to,
        usage=usage,
        prod=prod,
    )
