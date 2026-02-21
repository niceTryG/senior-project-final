from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models import Product

bp = Blueprint('cost', __name__, url_prefix="/cost")

@bp.route("/", methods=["GET", "POST"])
@login_required
def accountant_dashboard():
    if request.method == "POST":
        # You’ll add big logic here later (fabric usage, sewing pay, packaging cost, etc.)
        flash("Данные сохранены!", "success")
        return redirect(url_for("cost.accountant_dashboard"))

    return render_template("cost/accountant_dashboard.html")
