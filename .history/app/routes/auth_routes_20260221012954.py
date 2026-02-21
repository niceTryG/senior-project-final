from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_user, logout_user, current_user, login_required
from ..models import User
from ..extensions import db

auth_bp = Blueprint("auth", __name__)


# =========================
# LOGIN
# =========================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    error_key = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("main.dashboard"))
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