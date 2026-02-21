from flask import Blueprint, render_template
from flask_login import login_required

fabrics_bp = Blueprint("fabrics", __name__, url_prefix="/fabrics")


@fabrics_bp.route("/")
@login_required
def list():
    return render_template("fabrics/list.html")
