from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_user, logout_user, current_user, login_required
from ..models import User
from ..extensions import db
import os

auth_bp = Blueprint("auth", __name__)

# =========================
# LOGIN
# =========================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # If already logged in, send them to correct landing by role
    if current_user.is_authenticated:
        if getattr(current_user, "role", None) == "shop":
            return redirect(url_for("shop.dashboard_shop"))
        return redirect(url_for("main.dashboard"))

    error_key = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)

            # Respect ?next= if present (e.g., user tried to open a protected page)
            next_page = request.args.get("next")
            if next_page:
                return redirect(next_page)

            # ROLE-BASED LANDING
            if user.role == "shop":
                return redirect(url_for("shop.dashboard_shop"))

            return redirect(url_for("main.dashboard"))

        else:
            error_key = "error_wrong_credentials"

    return render_template("auth/login.html", error_key=error_key)


# =========================
# LOGOUT
# =========================
@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# =========================
# ADMIN: LIST USERS
# =========================
@auth_bp.route("/admin/users")
@login_required
def list_users():
    if not current_user.is_superadmin:
        abort(403)

    users = User.query.order_by(User.id.asc()).all()
    return render_template("admin/users_list.html", users=users)


# =========================
# ADMIN: CREATE USER
# =========================
@auth_bp.route("/admin/users/create", methods=["GET", "POST"])
@login_required
def create_user():
    if not current_user.is_superadmin:
        abort(403)

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "manager")

        if not username or not password:
            flash("Username and password required.", "danger")
            return redirect(url_for("auth.create_user"))

        if User.query.filter_by(username=username).first():
            flash("Username already exists.", "danger")
            return redirect(url_for("auth.create_user"))

        # Prevent web creation of superadmin
        if role == "admin":
            flash("Superadmin can only be created via CLI.", "danger")
            return redirect(url_for("auth.create_user"))

        user = User(username=username, role=role)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("User created successfully.", "success")
        return redirect(url_for("auth.list_users"))

    return render_template("admin/create_user.html")


# =========================
# ONE-TIME SETUP SUPERADMIN (Render)
# =========================
@auth_bp.route("/setup/<token>")
def setup_superadmin(token):
    # 1) must match env var token
    expected = os.environ.get("SETUP_TOKEN")
    if not expected or token != expected:
        abort(404)

    # 2) only works if NO admin user exists yet
    existing_admin = User.query.filter_by(role="admin").first()
    if existing_admin:
        return "Setup already completed. Admin exists."

    # 3) Read credentials from env (no hardcoding)
    username = os.environ.get("SETUP_ADMIN_USERNAME", "admin")
    password = os.environ.get("SETUP_ADMIN_PASSWORD")
    if not password:
        return "Missing SETUP_ADMIN_PASSWORD env var."

    user = User(username=username, role="admin")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return "Superadmin created. Go to /login and sign in. Then remove SETUP_TOKEN env var."