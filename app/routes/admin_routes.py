from flask import Blueprint, abort, render_template, url_for
from flask_login import current_user, login_required


admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin")
@login_required
def dashboard():
    if not current_user.is_admin:
        abort(403)

    cards = [
        {
            "title": "Factories",
            "description": "Manage factory records and configuration.",
            "href": url_for("auth.list_factories"),
            "button_label": "Open Factories",
            "disabled": False,
        },
        {
            "title": "Shops",
            "description": "Review shops, links, and shop access.",
            "href": url_for("auth.list_shops"),
            "button_label": "Open Shops",
            "disabled": False,
        },
        {
            "title": "Users",
            "description": "Create users and control admin, manager, or shop roles.",
            "href": url_for("auth.list_users"),
            "button_label": "Open Users",
            "disabled": False,
        },
        {
            "title": "Products",
            "description": "Go to product inventory, publishing, and admin delete controls.",
            "href": url_for("products.list_products"),
            "button_label": "Open Products",
            "disabled": False,
        },
        {
            "title": "Reports",
            "description": "Reserved for a future admin reporting overview.",
            "href": None,
            "button_label": "Coming Soon",
            "disabled": True,
        },
    ]

    return render_template("admin/dashboard.html", cards=cards)
