from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    session,
)
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy import or_, func
from datetime import datetime

from ..forms import SecurityWallPasswordForm
from ..models import User, Factory, Shop, ShopFactoryLink
from ..extensions import db
from ..user_identity import build_login_username, normalize_phone, normalize_username

import os


auth_bp = Blueprint("auth", __name__)
LOGIN_LOCK_THRESHOLD = 5
LOGIN_LOCK_MINUTES = 10


def _post_login_redirect_for(user):
    next_page = session.pop("post_security_redirect", None) or request.args.get("next")
    if next_page and str(next_page).startswith("/"):
        return redirect(next_page)

    if user.is_superadmin:
        return redirect(url_for("superadmin.dashboard"))

    if user.role == "shop":
        return redirect(url_for("shop.dashboard_shop"))

    return redirect(url_for("main.dashboard"))


def _find_user_by_login(login_value: str):
    normalized_login = normalize_username(login_value)
    normalized_phone = normalize_phone(normalized_login)

    clauses = [func.lower(User.username) == func.lower(normalized_login)]

    if normalized_phone:
        clauses.append(User.username == normalized_phone)
        clauses.append(User.phone == normalized_phone)

    return User.query.filter(or_(*clauses)).first()


def _username_taken(username: str, *, exclude_user_id: int | None = None) -> bool:
    normalized_username = normalize_username(username)
    if not normalized_username:
        return False

    clauses = [func.lower(User.username) == func.lower(normalized_username)]
    normalized_phone = normalize_phone(normalized_username)
    if normalized_phone:
        clauses.append(User.phone == normalized_phone)

    q = User.query.filter(or_(*clauses))
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    return q.first() is not None


def _phone_taken(phone: str | None, *, exclude_user_id: int | None = None) -> bool:
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return False

    q = User.query.filter(
        or_(
            User.phone == normalized_phone,
            func.lower(User.username) == func.lower(normalized_phone),
        )
    )
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    return q.first() is not None


# =========================
# LOGIN
# =========================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if getattr(current_user, "must_change_password", False):
            return redirect(url_for("auth.security_wall"))
        return _post_login_redirect_for(current_user)

    error_key = None
    error_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "1"

        user = _find_user_by_login(username)

        if user and user.is_login_locked():
            locked_until = getattr(user, "locked_until", None)
            error_message = (
                f"Too many failed attempts. Try again after {locked_until.strftime('%H:%M')}"
                if locked_until
                else "Too many failed attempts. Try again later."
            )
        elif user and user.check_password(password):
            user.clear_login_lock()
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=remember)
            session.permanent = True

            next_page = request.args.get("next")
            if next_page and next_page.startswith("/"):
                session["post_security_redirect"] = next_page

            if getattr(user, "must_change_password", False):
                flash("Update your temporary password before entering the workspace.", "warning")
                return redirect(url_for("auth.security_wall"))

            return _post_login_redirect_for(user)

        else:
            if user:
                user.register_failed_login(
                    threshold=LOGIN_LOCK_THRESHOLD,
                    minutes=LOGIN_LOCK_MINUTES,
                )
                db.session.commit()
                if user.is_login_locked():
                    locked_until = getattr(user, "locked_until", None)
                    error_message = (
                        f"Too many failed attempts. This account is locked until {locked_until.strftime('%H:%M')}."
                        if locked_until
                        else "Too many failed attempts. This account is temporarily locked."
                    )
            error_key = "error_wrong_credentials"

    return render_template("auth/login.html", error_key=error_key, error_message=error_message)


@auth_bp.route("/login/security", methods=["GET", "POST"])
@login_required
def security_wall():
    if not getattr(current_user, "must_change_password", False):
        return _post_login_redirect_for(current_user)

    form = SecurityWallPasswordForm()

    if request.method == "POST":
        if form.validate_on_submit():
            current_user.set_password(form.new_password.data or "")
            current_user.must_change_password = False
            current_user.clear_login_lock()
            db.session.commit()
            flash("Password updated successfully. Your workspace access is now unlocked.", "success")
            return _post_login_redirect_for(current_user)
        flash("Please review the new password fields and try again.", "danger")

    return render_template("auth/security_wall.html", form=form)


# =========================
# LOGOUT
# =========================
@auth_bp.route("/logout")
@login_required
def logout():
    session.pop("post_security_redirect", None)
    logout_user()
    return redirect(url_for("auth.login"))


def _can_manage_users() -> bool:
    return current_user.is_authenticated and current_user.is_admin


def _can_manage_factories() -> bool:
    return current_user.is_authenticated and current_user.is_superadmin


def _manageable_factories():
    if current_user.is_superadmin:
        return Factory.query.order_by(Factory.name.asc()).all()

    if current_user.factory_id:
        factory = Factory.query.get(current_user.factory_id)
        return [factory] if factory else []

    return []


def _manageable_shops(factory_id: int | None):
    if not factory_id:
        return []

    q = Shop.query.join(ShopFactoryLink, ShopFactoryLink.shop_id == Shop.id).filter(
        ShopFactoryLink.factory_id == factory_id
    )

    if not current_user.is_superadmin:
        q = q.filter(ShopFactoryLink.factory_id == current_user.factory_id)

    return q.order_by(Shop.name.asc()).distinct().all()


def _shop_linked_to_factory(shop_id: int, factory_id: int | None) -> bool:
    if not shop_id or not factory_id:
        return False

    link = ShopFactoryLink.query.filter_by(
        shop_id=shop_id,
        factory_id=factory_id,
    ).first()

    return link is not None


def _get_manageable_user_or_404(user_id: int):
    q = User.query.filter(User.id == user_id)

    if not current_user.is_superadmin:
        q = q.filter(User.factory_id == current_user.factory_id)

    user = q.first()
    if not user:
        abort(404)

    return user


def _get_factory_or_404(factory_id: int):
    factory = Factory.query.get(factory_id)
    if not factory:
        abort(404)
    return factory

def _manageable_factory_ids() -> list[int]:
    if current_user.is_superadmin:
        return [f.id for f in Factory.query.with_entities(Factory.id).all()]

    if current_user.factory_id:
        return [current_user.factory_id]

    return []


def _get_manageable_shop_or_404(shop_id: int):
    q = Shop.query.filter(Shop.id == shop_id)

    if not current_user.is_superadmin:
        q = q.join(ShopFactoryLink, ShopFactoryLink.shop_id == Shop.id).filter(
            ShopFactoryLink.factory_id == current_user.factory_id
        )

    shop = q.distinct().first()
    if not shop:
        abort(404)

    return shop
# =========================
# ADMIN: LIST SHOPS
# =========================
@auth_bp.route("/admin/shops")
@login_required
def list_shops():
    if not _can_manage_users():
        abort(403)

    search = (request.args.get("q") or "").strip()
    factory_filter = request.args.get("factory_id", type=int)

    q = Shop.query

    if current_user.is_superadmin:
        if factory_filter:
            q = q.join(ShopFactoryLink, ShopFactoryLink.shop_id == Shop.id).filter(
                ShopFactoryLink.factory_id == factory_filter
            )
    else:
        q = q.join(ShopFactoryLink, ShopFactoryLink.shop_id == Shop.id).filter(
            ShopFactoryLink.factory_id == current_user.factory_id
        )

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Shop.name.ilike(like),
                Shop.location.ilike(like),
                Shop.note.ilike(like),
            )
        )

    shops = q.order_by(Shop.id.desc()).distinct().all()
    factories = _manageable_factories()

    shop_rows = []
    for shop in shops:
        links_q = ShopFactoryLink.query.filter_by(shop_id=shop.id)

        if not current_user.is_superadmin:
            links_q = links_q.filter(
                ShopFactoryLink.factory_id == current_user.factory_id
            )

        links = links_q.all()
        linked_factory_ids = [x.factory_id for x in links]

        linked_factories = []
        if linked_factory_ids:
            linked_factories = (
                Factory.query.filter(Factory.id.in_(linked_factory_ids))
                .order_by(Factory.name.asc())
                .all()
            )

        users_count = User.query.filter(User.shop_id == shop.id).count()

        shop_rows.append(
            {
                "shop": shop,
                "linked_factories": linked_factories,
                "linked_factory_count": len(linked_factories),
                "users_count": users_count,
            }
        )

    return render_template(
        "admin/shops_list.html",
        shop_rows=shop_rows,
        factories=factories,
        q=search,
        selected_factory_id=factory_filter,
    )


# =========================
# ADMIN: CREATE SHOP
# =========================
@auth_bp.route("/admin/shops/create", methods=["GET", "POST"])
@login_required
def create_shop():
    if not _can_manage_users():
        abort(403)

    factories = _manageable_factories()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        location = (request.form.get("location") or "").strip() or None
        note = (request.form.get("note") or "").strip() or None
        is_active = request.form.get("is_active") == "1"

        selected_factory_ids = request.form.getlist("factory_ids")
        selected_factory_ids = [
            int(x) for x in selected_factory_ids if str(x).isdigit()
        ]

        allowed_factory_ids = set(_manageable_factory_ids())
        selected_factory_ids = [
            x for x in selected_factory_ids if x in allowed_factory_ids
        ]

        if not name:
            flash("Shop name is required.", "danger")
            return redirect(url_for("auth.create_shop"))

        if not selected_factory_ids:
            flash("Ð’Ñ‹Ð±ÐµÑ€Ð¸Ñ‚Ðµ Ñ…Ð¾Ñ‚Ñ Ð±Ñ‹ Ð¾Ð´Ð½Ñƒ Ñ„Ð°Ð±Ñ€Ð¸ÐºÑƒ.", "danger")
            return redirect(url_for("auth.create_shop"))

        existing = Shop.query.filter(Shop.name == name).first()
        if existing:
            flash("ÐœÐ°Ð³Ð°Ð·Ð¸Ð½ Ñ Ñ‚Ð°ÐºÐ¸Ð¼ Ð½Ð°Ð·Ð²Ð°Ð½Ð¸ÐµÐ¼ ÑƒÐ¶Ðµ ÑÑƒÑ‰ÐµÑÑ‚Ð²ÑƒÐµÑ‚.", "danger")
            return redirect(url_for("auth.create_shop"))
        legacy_factory_id = selected_factory_ids[0]
        shop = Shop(
            factory_id=legacy_factory_id,
            name=name,
            location=location,
            note=note,
            is_active=is_active,
        )
        db.session.add(shop)
        db.session.flush()

        for factory_id in selected_factory_ids:
            db.session.add(
                ShopFactoryLink(
                    shop_id=shop.id,
                    factory_id=factory_id,
                )
            )

        db.session.commit()

        flash("Shop created successfully.", "success")
        return redirect(url_for("auth.list_shops"))

    preselected_factory_ids = _manageable_factory_ids() if not current_user.is_superadmin else []

    return render_template(
        "admin/create_shop.html",
        factories=factories,
        selected_factory_ids=preselected_factory_ids,
    )


# =========================
# ADMIN: EDIT SHOP
# =========================
@auth_bp.route("/admin/shops/<int:shop_id>/edit", methods=["GET", "POST"])
@login_required
def edit_shop(shop_id):
    if not _can_manage_users():
        abort(403)

    shop = _get_manageable_shop_or_404(shop_id)
    factories = _manageable_factories()

    existing_links = ShopFactoryLink.query.filter_by(shop_id=shop.id).all()
    existing_factory_ids = [x.factory_id for x in existing_links]

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        location = (request.form.get("location") or "").strip() or None
        note = (request.form.get("note") or "").strip() or None
        is_active = request.form.get("is_active") == "1"

        selected_factory_ids = request.form.getlist("factory_ids")
        selected_factory_ids = [
            int(x) for x in selected_factory_ids if str(x).isdigit()
        ]

        allowed_factory_ids = set(_manageable_factory_ids())
        selected_factory_ids = [
            x for x in selected_factory_ids if x in allowed_factory_ids
        ]

        if not name:
            flash("Shop name is required.", "danger")
            return redirect(url_for("auth.edit_shop", shop_id=shop.id))

        if not selected_factory_ids:
            flash("Ð’Ñ‹Ð±ÐµÑ€Ð¸Ñ‚Ðµ Ñ…Ð¾Ñ‚Ñ Ð±Ñ‹ Ð¾Ð´Ð½Ñƒ Ñ„Ð°Ð±Ñ€Ð¸ÐºÑƒ.", "danger")
            return redirect(url_for("auth.edit_shop", shop_id=shop.id))

        existing = Shop.query.filter(
            Shop.name == name,
            Shop.id != shop.id,
        ).first()
        if existing:
            flash("Ð”Ñ€ÑƒÐ³Ð¾Ð¹ Ð¼Ð°Ð³Ð°Ð·Ð¸Ð½ Ñ Ñ‚Ð°ÐºÐ¸Ð¼ Ð½Ð°Ð·Ð²Ð°Ð½Ð¸ÐµÐ¼ ÑƒÐ¶Ðµ ÑÑƒÑ‰ÐµÑÑ‚Ð²ÑƒÐµÑ‚.", "danger")
            return redirect(url_for("auth.edit_shop", shop_id=shop.id))

        shop.name = name
        shop.location = location
        shop.note = note
        shop.is_active = is_active
        shop.factory_id = selected_factory_ids[0]

        if current_user.is_superadmin:
            ShopFactoryLink.query.filter_by(shop_id=shop.id).delete()
            for factory_id in selected_factory_ids:
                db.session.add(
                    ShopFactoryLink(
                        shop_id=shop.id,
                        factory_id=factory_id,
                    )
                )
        else:
            # factory admin can only manage their own links
            ShopFactoryLink.query.filter_by(
                shop_id=shop.id,
                factory_id=current_user.factory_id,
            ).delete()

            for factory_id in selected_factory_ids:
                if factory_id == current_user.factory_id:
                    db.session.add(
                        ShopFactoryLink(
                            shop_id=shop.id,
                            factory_id=factory_id,
                        )
                    )

        db.session.commit()

        flash("Shop updated successfully.", "success")
        return redirect(url_for("auth.list_shops"))

    visible_selected_factory_ids = [
        fid for fid in existing_factory_ids if fid in _manageable_factory_ids()
    ]

    return render_template(
        "admin/edit_shop.html",
        shop=shop,
        factories=factories,
        selected_factory_ids=visible_selected_factory_ids,
    )
# =========================
# ADMIN: LIST USERS
# =========================
@auth_bp.route("/admin/users")
@login_required
def list_users():
    if not _can_manage_users():
        abort(403)

    search = (request.args.get("q") or "").strip()
    role_filter = (request.args.get("role") or "").strip()
    factory_filter = request.args.get("factory_id", type=int)

    q = User.query

    if current_user.is_superadmin:
        if factory_filter:
            q = q.filter(User.factory_id == factory_filter)
    else:
        q = q.filter(User.factory_id == current_user.factory_id)

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                User.username.ilike(like),
                User.full_name.ilike(like),
                User.phone.ilike(like),
            )
        )

    if role_filter:
        q = q.filter(User.role == role_filter)

    users = q.order_by(User.id.desc()).all()

    factories = _manageable_factories()
    shops = []
    if current_user.is_superadmin and factory_filter:
        shops = _manageable_shops(factory_filter)
    elif not current_user.is_superadmin and current_user.factory_id:
        shops = _manageable_shops(current_user.factory_id)

    return render_template(
        "admin/users_list.html",
        users=users,
        factories=factories,
        shops=shops,
        q=search,
        selected_role=role_filter,
        selected_factory_id=factory_filter,
    )


# =========================
# ADMIN: CREATE USER
# =========================
@auth_bp.route("/admin/users/create", methods=["GET", "POST"])
@login_required
def create_user():
    if not _can_manage_users():
        abort(403)

    factories = _manageable_factories()

    if request.method == "POST":
        username_input = request.form.get("username", "").strip()
        full_name = (request.form.get("full_name") or "").strip() or None
        phone = normalize_phone(request.form.get("phone"))
        password = request.form.get("password", "")
        role = (request.form.get("role", "manager") or "manager").strip()
        factory_id = request.form.get("factory_id", type=int)
        shop_id = request.form.get("shop_id", type=int)
        username = build_login_username(username_input, phone)

        if not username or not password:
            flash("Username or phone, and password, are required.", "danger")
            return redirect(url_for("auth.create_user"))

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return redirect(url_for("auth.create_user"))

        if _username_taken(username):
            flash("Username already exists.", "danger")
            return redirect(url_for("auth.create_user"))

        if _phone_taken(phone):
            flash("Phone number already exists.", "danger")
            return redirect(url_for("auth.create_user"))

        allowed_roles = {"manager", "viewer", "shop", "accountant"}

        if current_user.is_superadmin:
            allowed_roles.add("admin")

        if role not in allowed_roles:
            flash("Invalid role.", "danger")
            return redirect(url_for("auth.create_user"))

        if current_user.is_superadmin:
            if role != "admin" and not factory_id:
                flash("Factory is required for non-admin users.", "danger")
                return redirect(url_for("auth.create_user"))
        else:
            factory_id = current_user.factory_id
            if role == "admin":
                flash("Factory admin cannot create another admin.", "danger")
                return redirect(url_for("auth.create_user"))

        if role == "shop" and not shop_id:
            flash("Shop is required for shop users.", "danger")
            return redirect(url_for("auth.create_user"))

        if shop_id:
            shop = Shop.query.get(shop_id)
            if not shop:
                flash("Selected shop not found.", "danger")
                return redirect(url_for("auth.create_user"))

            effective_factory_id = factory_id if current_user.is_superadmin else current_user.factory_id

            if not _shop_linked_to_factory(shop_id=shop.id, factory_id=effective_factory_id):
                flash("Selected shop is not linked to selected factory.", "danger")
                return redirect(url_for("auth.create_user"))

        user = User(
            username=username,
            full_name=full_name,
            phone=phone,
            role=role,
            factory_id=factory_id if role != "admin" or not current_user.is_superadmin else None,
            shop_id=shop_id if role == "shop" else None,
            must_change_password=True,
        )
        user.set_password(password)
        user.clear_login_lock()

        db.session.add(user)
        db.session.commit()

        flash(f"User created successfully. Login: {user.username}. First login will require a private password update.", "success")
        return redirect(url_for("auth.list_users"))

    selected_factory_id = None
    if not current_user.is_superadmin:
        selected_factory_id = current_user.factory_id

    shops = _manageable_shops(selected_factory_id)

    return render_template(
        "admin/create_user.html",
        factories=factories,
        shops=shops,
        selected_factory_id=selected_factory_id,
    )


# =========================
# ADMIN: EDIT USER
# =========================
@auth_bp.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def edit_user(user_id):
    if not _can_manage_users():
        abort(403)

    user = _get_manageable_user_or_404(user_id)
    factories = _manageable_factories()

    if request.method == "POST":
        username_input = request.form.get("username", "").strip()
        full_name = (request.form.get("full_name") or "").strip() or None
        phone = normalize_phone(request.form.get("phone"))
        role = (request.form.get("role", user.role) or user.role).strip()
        factory_id = request.form.get("factory_id", type=int)
        shop_id = request.form.get("shop_id", type=int)
        username = build_login_username(username_input, phone)

        if not username:
            flash("Username or phone is required.", "danger")
            return redirect(url_for("auth.edit_user", user_id=user.id))

        if _username_taken(username, exclude_user_id=user.id):
            flash("Username already exists.", "danger")
            return redirect(url_for("auth.edit_user", user_id=user.id))

        if _phone_taken(phone, exclude_user_id=user.id):
            flash("Phone number already exists.", "danger")
            return redirect(url_for("auth.edit_user", user_id=user.id))

        allowed_roles = {"manager", "viewer", "shop", "accountant"}

        if current_user.is_superadmin:
            allowed_roles.add("admin")

        if role not in allowed_roles:
            flash("Invalid role.", "danger")
            return redirect(url_for("auth.edit_user", user_id=user.id))

        if current_user.is_superadmin:
            if role != "admin" and not factory_id:
                flash("Factory is required for non-admin users.", "danger")
                return redirect(url_for("auth.edit_user", user_id=user.id))
        else:
            factory_id = current_user.factory_id
            if role == "admin":
                flash("Factory admin cannot assign admin role.", "danger")
                return redirect(url_for("auth.edit_user", user_id=user.id))

        if role == "shop" and not shop_id:
            flash("Shop is required for shop users.", "danger")
            return redirect(url_for("auth.edit_user", user_id=user.id))

        if shop_id:
            shop = Shop.query.get(shop_id)
            if not shop:
                flash("Selected shop not found.", "danger")
                return redirect(url_for("auth.edit_user", user_id=user.id))

            effective_factory_id = factory_id if current_user.is_superadmin else current_user.factory_id

            if not _shop_linked_to_factory(shop_id=shop.id, factory_id=effective_factory_id):
                flash("Selected shop is not linked to selected factory.", "danger")
                return redirect(url_for("auth.edit_user", user_id=user.id))

        user.username = username
        user.full_name = full_name
        user.phone = phone
        user.role = role
        user.factory_id = factory_id if role != "admin" or not current_user.is_superadmin else None
        user.shop_id = shop_id if role == "shop" else None

        db.session.commit()

        flash("User updated successfully.", "success")
        return redirect(url_for("auth.list_users"))

    selected_factory_id = user.factory_id if user.factory_id else None
    shops = _manageable_shops(selected_factory_id)

    return render_template(
        "admin/edit_user.html",
        edit_user_obj=user,
        factories=factories,
        shops=shops,
        selected_factory_id=selected_factory_id,
    )


@auth_bp.route("/admin/users/<int:user_id>/password", methods=["POST"])
@login_required
def change_user_password(user_id):
    if not _can_manage_users():
        abort(403)

    user = _get_manageable_user_or_404(user_id)

    new_password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not new_password:
        flash("Password is required.", "danger")
        return redirect(url_for("auth.edit_user", user_id=user.id))

    if len(new_password) < 6:
        flash("Password must be at least 6 characters.", "danger")
        return redirect(url_for("auth.edit_user", user_id=user.id))

    if new_password != confirm_password:
        flash("Passwords do not match.", "danger")
        return redirect(url_for("auth.edit_user", user_id=user.id))

    user.set_password(new_password)
    user.must_change_password = True
    user.clear_login_lock()
    db.session.commit()

    flash("Password updated successfully. The user will be asked to set a private password at next login.", "success")
    return redirect(url_for("auth.edit_user", user_id=user.id))


@auth_bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id):
    if not _can_manage_users():
        abort(403)

    user = _get_manageable_user_or_404(user_id)
    next_url = request.form.get("next") or request.referrer or url_for("auth.list_users")

    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(next_url)

    if user.is_superadmin:
        flash("Superadmin cannot be deleted from this screen.", "danger")
        return redirect(next_url)

    if user.is_admin and not current_user.is_superadmin:
        flash("Workspace owner account cannot be deleted here.", "danger")
        return redirect(next_url)

    db.session.delete(user)
    db.session.commit()

    flash("User deleted successfully.", "success")
    return redirect(next_url)


@auth_bp.route("/admin/shops/by-factory")
@login_required
def shops_by_factory():
    if not _can_manage_users():
        abort(403)

    factory_id = request.args.get("factory_id", type=int)
    if not factory_id:
        return {"items": []}

    q = Shop.query.join(ShopFactoryLink, ShopFactoryLink.shop_id == Shop.id).filter(
        ShopFactoryLink.factory_id == factory_id
    )

    if not current_user.is_superadmin:
        q = q.filter(ShopFactoryLink.factory_id == current_user.factory_id)

    shops = q.order_by(Shop.name.asc()).distinct().all()

    return {
        "items": [
            {
                "id": s.id,
                "name": s.name,
            }
            for s in shops
        ]
    }


# =========================
# ADMIN: LIST FACTORIES
# =========================
@auth_bp.route("/admin/factories")
@login_required
def list_factories():
    if not _can_manage_factories():
        abort(403)

    search = (request.args.get("q") or "").strip()

    q = Factory.query

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Factory.name.ilike(like),
                Factory.owner_name.ilike(like),
                Factory.location.ilike(like),
                Factory.phone.ilike(like),
            )
        )

    factories = q.order_by(Factory.id.desc()).all()

    factory_rows = []
    for f in factories:
        users_count = User.query.filter(User.factory_id == f.id).count()
        shops_count = (
            db.session.query(ShopFactoryLink.shop_id)
            .filter(ShopFactoryLink.factory_id == f.id)
            .distinct()
            .count()
        )

        factory_rows.append(
            {
                "factory": f,
                "users_count": users_count,
                "shops_count": shops_count,
            }
        )

    return render_template(
        "admin/factories_list.html",
        factory_rows=factory_rows,
        q=search,
    )


# =========================
# ADMIN: CREATE FACTORY
# =========================
@auth_bp.route("/admin/factories/create", methods=["GET", "POST"])
@login_required
def create_factory():
    if not _can_manage_factories():
        abort(403)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        location = (request.form.get("location") or "").strip() or None
        owner_name = (request.form.get("owner_name") or "").strip() or None
        phone = (request.form.get("phone") or "").strip() or None
        note = (request.form.get("note") or "").strip() or None

        if not name:
            flash("Factory name is required.", "danger")
            return redirect(url_for("auth.create_factory"))

        existing = Factory.query.filter(Factory.name == name).first()
        if existing:
            flash("Factory with this name already exists.", "danger")
            return redirect(url_for("auth.create_factory"))

        factory = Factory(
            name=name,
            location=location,
            owner_name=owner_name,
            phone=phone,
            note=note,
        )
        db.session.add(factory)
        db.session.commit()

        flash("Factory created successfully.", "success")
        return redirect(url_for("auth.list_factories"))

    return render_template("admin/create_factory.html")


# =========================
# ADMIN: EDIT FACTORY
# =========================
@auth_bp.route("/admin/factories/<int:factory_id>/edit", methods=["GET", "POST"])
@login_required
def edit_factory(factory_id):
    if not _can_manage_factories():
        abort(403)

    factory = _get_factory_or_404(factory_id)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        location = (request.form.get("location") or "").strip() or None
        owner_name = (request.form.get("owner_name") or "").strip() or None
        phone = (request.form.get("phone") or "").strip() or None
        note = (request.form.get("note") or "").strip() or None

        if not name:
            flash("Factory name is required.", "danger")
            return redirect(url_for("auth.edit_factory", factory_id=factory.id))

        existing = Factory.query.filter(
            Factory.name == name,
            Factory.id != factory.id,
        ).first()
        if existing:
            flash("Another factory with this name already exists.", "danger")
            return redirect(url_for("auth.edit_factory", factory_id=factory.id))

        factory.name = name
        factory.location = location
        factory.owner_name = owner_name
        factory.phone = phone
        factory.note = note

        db.session.commit()

        flash("Factory updated successfully.", "success")
        return redirect(url_for("auth.list_factories"))

    users_count = User.query.filter(User.factory_id == factory.id).count()
    shops_count = (
        db.session.query(ShopFactoryLink.shop_id)
        .filter(ShopFactoryLink.factory_id == factory.id)
        .distinct()
        .count()
    )

    return render_template(
        "admin/edit_factory.html",
        factory=factory,
        users_count=users_count,
        shops_count=shops_count,
    )


# =========================
# ONE-TIME SETUP SUPERADMIN (Render)
# =========================
@auth_bp.route("/setup/<token>")
def setup_superadmin(token):
    expected = os.environ.get("SETUP_TOKEN")
    if not expected or token != expected:
        abort(404)

    existing_admin = User.query.filter_by(role="admin").first()
    if existing_admin:
        return "Setup already completed. Admin exists."

    username = os.environ.get("SETUP_ADMIN_USERNAME", "admin")
    password = os.environ.get("SETUP_ADMIN_PASSWORD")
    if not password:
        return "Missing SETUP_ADMIN_PASSWORD env var."

    user = User(username=username, role="admin")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return "Superadmin created. Go to /login and sign in. Then remove SETUP_TOKEN env var." 

