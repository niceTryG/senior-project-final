"""
Superadmin panel — platform owner's god-view interface.
Access: role == 'superadmin'  (or legacy admin with no factory)
Prefix: /superadmin
"""
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, abort, render_template, redirect, url_for, request, flash
from flask_login import current_user, login_required
from sqlalchemy import func, distinct

from ..extensions import db
from ..models import Factory, Shop, User, Product, Sale, Fabric

superadmin_bp = Blueprint("superadmin", __name__, url_prefix="/superadmin")


# ---------------------------------------------------------------------------
# Guard decorator
# ---------------------------------------------------------------------------

def superadmin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.is_superadmin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _platform_stats():
    """Compute high-level KPIs for the overview dashboard."""
    total_factories = Factory.query.count()
    total_users = User.query.filter(User.role != "superadmin").count()
    total_shops = Shop.query.count()
    total_products = Product.query.count()

    # Users who have logged in in the last 30 days
    since_30d = datetime.utcnow() - timedelta(days=30)
    new_users_30d = User.query.filter(
        User.role != "superadmin",
        User.last_login_at >= since_30d,
    ).count()

    # Sales in last 30 days (join via product → factory)
    sales_30d = Sale.query.filter(Sale.created_at >= since_30d).count()

    # Active factories (have at least one user)
    active_factories = (
        db.session.query(func.count(distinct(User.factory_id)))
        .filter(User.factory_id.isnot(None))
        .scalar()
        or 0
    )

    # Role breakdown
    role_counts = (
        db.session.query(User.role, func.count(User.id))
        .filter(User.role != "superadmin")
        .group_by(User.role)
        .all()
    )

    return {
        "total_factories": total_factories,
        "total_users": total_users,
        "total_shops": total_shops,
        "total_products": total_products,
        "new_users_30d": new_users_30d,
        "sales_30d": sales_30d,
        "active_factories": active_factories,
        "role_counts": {role: count for role, count in role_counts},
    }


def _tenant_rows():
    """Return all factories enriched with counts."""
    factories = Factory.query.order_by(Factory.created_at.desc()).all()

    # User counts per factory
    user_counts = dict(
        db.session.query(User.factory_id, func.count(User.id))
        .filter(User.factory_id.isnot(None))
        .group_by(User.factory_id)
        .all()
    )
    # Product counts per factory
    product_counts = dict(
        db.session.query(Product.factory_id, func.count(Product.id))
        .group_by(Product.factory_id)
        .all()
    )
    # Shop counts per factory
    shop_counts = dict(
        db.session.query(Shop.factory_id, func.count(Shop.id))
        .group_by(Shop.factory_id)
        .all()
    )
    # Latest sale per factory via products
    latest_sale_sq = (
        db.session.query(
            Product.factory_id,
            func.max(Sale.created_at).label("last_sale"),
        )
        .join(Sale, Sale.product_id == Product.id)
        .group_by(Product.factory_id)
        .subquery()
    )
    latest_sales = dict(
        db.session.query(
            latest_sale_sq.c.factory_id, latest_sale_sq.c.last_sale
        ).all()
    )

    rows = []
    for f in factories:
        rows.append(
            {
                "factory": f,
                "user_count": user_counts.get(f.id, 0),
                "product_count": product_counts.get(f.id, 0),
                "shop_count": shop_counts.get(f.id, 0),
                "last_sale": latest_sales.get(f.id),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@superadmin_bp.route("/")
@login_required
@superadmin_required
def dashboard():
    stats = _platform_stats()
    # Recent signups (all roles except superadmin)
    recent_users = (
        User.query.filter(User.role != "superadmin")
        .order_by(User.id.desc())
        .limit(8)
        .all()
    )
    # Top factories by user count
    top_tenant_rows = sorted(_tenant_rows(), key=lambda r: r["user_count"], reverse=True)[:5]

    return render_template(
        "superadmin/dashboard.html",
        stats=stats,
        recent_users=recent_users,
        top_tenant_rows=top_tenant_rows,
        active_section="dashboard",
    )


@superadmin_bp.route("/tenants")
@login_required
@superadmin_required
def tenants():
    q = request.args.get("q", "").strip()
    rows = _tenant_rows()
    if q:
        rows = [r for r in rows if q.lower() in r["factory"].name.lower()]
    return render_template(
        "superadmin/tenants.html",
        rows=rows,
        q=q,
        active_section="tenants",
    )


@superadmin_bp.route("/tenants/<int:tenant_id>")
@login_required
@superadmin_required
def tenant_detail(tenant_id):
    factory = Factory.query.get_or_404(tenant_id)
    users = (
        User.query.filter_by(factory_id=tenant_id)
        .order_by(User.role, User.username)
        .all()
    )
    shops = Shop.query.filter_by(factory_id=tenant_id).all()
    products = (
        Product.query.filter_by(factory_id=tenant_id).order_by(Product.id.desc()).limit(20).all()
    )
    total_products = Product.query.filter_by(factory_id=tenant_id).count()
    materials = Fabric.query.filter_by(factory_id=tenant_id).count()

    # Recent sales via products belonging to this factory
    recent_sales = (
        Sale.query.join(Product, Sale.product_id == Product.id)
        .filter(Product.factory_id == tenant_id)
        .order_by(Sale.created_at.desc())
        .limit(10)
        .all()
    )
    total_sales = (
        Sale.query.join(Product, Sale.product_id == Product.id)
        .filter(Product.factory_id == tenant_id)
        .count()
    )

    return render_template(
        "superadmin/tenant_detail.html",
        factory=factory,
        users=users,
        shops=shops,
        products=products,
        total_products=total_products,
        materials=materials,
        recent_sales=recent_sales,
        total_sales=total_sales,
        active_section="tenants",
    )


@superadmin_bp.route("/users")
@login_required
@superadmin_required
def users():
    role_filter = request.args.get("role", "").strip()
    factory_filter = request.args.get("factory_id", "").strip()
    q = request.args.get("q", "").strip()

    query = User.query.filter(User.role != "superadmin")

    if role_filter:
        query = query.filter(User.role == role_filter)
    if factory_filter:
        query = query.filter(User.factory_id == int(factory_filter))
    if q:
        query = query.filter(
            db.or_(
                User.username.ilike(f"%{q}%"),
                User.full_name.ilike(f"%{q}%"),
                User.phone.ilike(f"%{q}%"),
            )
        )

    all_users = query.order_by(User.id.desc()).all()
    factories = Factory.query.order_by(Factory.name).all()

    return render_template(
        "superadmin/users.html",
        all_users=all_users,
        factories=factories,
        role_filter=role_filter,
        factory_filter=factory_filter,
        q=q,
        active_section="users",
    )


@superadmin_bp.route("/users/<int:user_id>")
@login_required
@superadmin_required
def user_detail(user_id):
    user = User.query.get_or_404(user_id)
    factories = Factory.query.order_by(Factory.name).all()
    recent_sales = (
        Sale.query.filter_by(created_by_id=user_id)
        .join(Product, Sale.product_id == Product.id)
        .order_by(Sale.created_at.desc())
        .limit(10)
        .all()
    )
    return render_template(
        "superadmin/user_detail.html",
        user=user,
        factories=factories,
        recent_sales=recent_sales,
        active_section="users",
        ROLES=["admin", "manager", "accountant", "viewer", "shop"],
    )


@superadmin_bp.route("/users/<int:user_id>/set-role", methods=["POST"])
@login_required
@superadmin_required
def set_user_role(user_id):
    user = User.query.get_or_404(user_id)
    new_role = request.form.get("role", "").strip()
    allowed = {"admin", "manager", "accountant", "viewer", "shop"}
    if new_role not in allowed:
        flash("Invalid role.", "danger")
        return redirect(url_for("superadmin.user_detail", user_id=user_id))

    user.role = new_role
    db.session.commit()
    flash(f"Role updated to '{new_role}' for {user.username}.", "success")
    return redirect(url_for("superadmin.user_detail", user_id=user_id))


@superadmin_bp.route("/users/<int:user_id>/toggle-lock", methods=["POST"])
@login_required
@superadmin_required
def toggle_user_lock(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_login_locked():
        user.clear_login_lock()
        flash(f"Account unlocked for {user.username}.", "success")
    else:
        # Lock indefinitely (24 hours)
        user.locked_until = datetime.utcnow() + timedelta(hours=24)
        flash(f"Account locked for {user.username} (24 h).", "warning")
    db.session.commit()
    return redirect(url_for("superadmin.user_detail", user_id=user_id))


@superadmin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@superadmin_required
def reset_user_password(user_id):
    user = User.query.get_or_404(user_id)
    new_pw = request.form.get("new_password", "").strip()
    if len(new_pw) < 6:
        flash("Password must be at least 6 characters.", "danger")
        return redirect(url_for("superadmin.user_detail", user_id=user_id))

    user.set_password(new_pw)
    user.must_change_password = True
    db.session.commit()
    flash(f"Password reset for {user.username}. They must change it on next login.", "success")
    return redirect(url_for("superadmin.user_detail", user_id=user_id))
