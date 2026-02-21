from flask import Blueprint, render_template
from flask_login import login_required

factory_bp = Blueprint("factory", __name__, url_prefix="/factory")


@factory_bp.route("/produce", methods=["GET"])
@login_required
def produce():
    # Temporary page so the dashboard link works.
    # Next step: we'll build the real "produce today" workflow here.
    return render_template("factory/produce.html")
