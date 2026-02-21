from flask import Blueprint, render_template, make_response
from flask_login import login_required
from xhtml2pdf import pisa
from io import BytesIO

from ..services.product_service import ProductService

manager_report_bp = Blueprint("manager_report", __name__)

product_service = ProductService()


@manager_report_bp.route("/manager/report")
@login_required
def manager_report():
    report = product_service.get_manager_financial_report()
    return render_template("manager/report.html", report=report)


@manager_report_bp.route("/manager/report/pdf")
@login_required
def manager_report_pdf():
    report = product_service.get_manager_financial_report()

    html = render_template("manager/report_pdf.html", report=report)

    pdf = BytesIO()
    pisa.CreatePDF(BytesIO(html.encode("utf-8")), dest=pdf)

    response = make_response(pdf.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=manager_report.pdf"

    return response
