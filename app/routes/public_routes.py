import os
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    render_template,
    abort,
    current_app,
    request,
    send_from_directory,
    redirect,
    url_for,
    session,
    flash,
)
from flask_babel import refresh
from flask_login import current_user, login_user
from urllib.parse import quote
from werkzeug.security import generate_password_hash

from sqlalchemy import or_, text, inspect, func

from ..forms import (
    ONBOARDING_PHONE_COUNTRY_CHOICES,
    OnboardingLaunchForm,
    OnboardingOwnerForm,
    OnboardingShopForm,
    OnboardingTeamForm,
    OnboardingVerifyForm,
    OnboardingWorkspaceForm,
)
from ..models import (
    Product,
    Factory,
    User,
    Shop,
    ShopFactoryLink,
    OnboardingTelegramVerification,
    TelegramLink,
)
from ..extensions import db
from ..services.garment_analysis_service import GarmentImageAnalysisService
from ..translations import t as translate
from ..user_identity import build_login_username, normalize_phone, normalize_username

public_bp = Blueprint("public", __name__)
garment_analysis_service = GarmentImageAnalysisService()


ONBOARDING_SESSION_KEY = "adras_onboarding"
ONBOARDING_STEPS = ("account", "verify", "workspace", "shop", "team", "review")


def _public_phone() -> str:
    return (current_app.config.get("PUBLIC_PHONE") or "+998 99 000 00 00").strip()


def _public_phone_href() -> str:
    return normalize_phone(_public_phone()) or "+998990000000"


def _telegram_url() -> str:
    return (current_app.config.get("PUBLIC_TELEGRAM_URL") or "").strip()


def _telegram_bot_url() -> str:
    return (
        current_app.config.get("PUBLIC_TELEGRAM_BOT_URL")
        or "https://t.me/minimoda_sklad_bot"
    ).strip()


def _telegram_signup_url(token: str | None) -> str:
    clean_token = str(token or "").strip()
    if not clean_token:
        return _telegram_bot_url()

    base = _telegram_bot_url().rstrip("/")
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}start={quote(f'signup_{clean_token}')}"


def _split_owner_phone_parts(phone: str | None) -> tuple[str, str]:
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return "+998", ""

    for country_code, _label in ONBOARDING_PHONE_COUNTRY_CHOICES:
        if normalized_phone.startswith(country_code):
            return country_code, normalized_phone[len(country_code):]

    return "+998", normalized_phone.lstrip("+")


def _owner_verification_record(state):
    owner_state = state.get("owner") or {}
    token = (owner_state.get("telegram_token") or "").strip()
    if not token:
        return None

    return OnboardingTelegramVerification.query.filter_by(token=token).first()


def _owner_is_verified(state) -> bool:
    verification = _owner_verification_record(state)
    return bool(verification and verification.is_verified())


def _ensure_owner_verification(state):
    owner_state = state.get("owner") or {}
    phone = normalize_phone(owner_state.get("phone"))
    if not phone:
        return None

    full_name = (owner_state.get("full_name") or "").strip() or None
    existing = _owner_verification_record(state)

    if existing and normalize_phone(existing.phone) == phone:
        existing.full_name = full_name
        if not existing.is_verified():
            existing.expires_at = datetime.utcnow() + timedelta(minutes=30)
        db.session.commit()
        return existing

    if existing:
        db.session.delete(existing)
        db.session.commit()

    verification = OnboardingTelegramVerification.generate(
        phone=phone,
        full_name=full_name,
        minutes=30,
    )
    db.session.add(verification)
    db.session.commit()

    state["owner"]["telegram_token"] = verification.token
    _save_onboarding_state(state)
    return verification


def _tg_order_link(product=None, qty=1):
    base = _telegram_url() or "https://t.me/minimoda_sklad_bot"

    # If no product was provided, return the bot link (no prefilled text)
    if not product:
        return base

    # Defensive: if product has no id, also fallback
    pid = getattr(product, "id", None)
    if not pid:
        return base

    code = f"MM-{pid:05d}"
    name = getattr(product, "name", "") or ""

    # Clamp qty to a sane int
    try:
        qty_int = int(qty)
    except Exception:
        qty_int = 1

    if qty_int < 1:
        qty_int = 1
    if qty_int > 999:
        qty_int = 999

    text_value = (
        "🧾 Adras order\n"
        f"📌 Code: {code}\n"
        f"👕 Name: {name}\n"
        f"🔢 Qty: {qty_int}\n\n"
        "📞 Phone:\n"
        "📍 Address:"
    )

    return f"{base}?text={quote(text_value)}"


def _product_column_exists(column_name: str) -> bool:
    """
    Cross-db safe check:
    - SQLite: PRAGMA table_info(products)
    - Postgres/MySQL/others: SQLAlchemy inspector
    """
    try:
        dialect = db.engine.dialect.name

        if dialect == "sqlite":
            cols = db.session.execute(text("PRAGMA table_info(products)")).fetchall()
            col_names = [c[1] for c in cols]
            return column_name in col_names

        inspector = inspect(db.engine)
        columns = inspector.get_columns("products")
        col_names = [c["name"] for c in columns]
        return column_name in col_names

    except Exception:
        return False


def _username_taken(username: str) -> bool:
    normalized_username = normalize_username(username)
    if not normalized_username:
        return False

    normalized_phone = normalize_phone(normalized_username)
    clauses = [func.lower(User.username) == func.lower(normalized_username)]
    if normalized_phone:
        clauses.append(User.phone == normalized_phone)

    return User.query.filter(or_(*clauses)).first() is not None


def _phone_taken(phone: str | None) -> bool:
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return False

    return (
        User.query
        .filter(
            or_(
                User.phone == normalized_phone,
                func.lower(User.username) == func.lower(normalized_phone),
            )
        )
        .first()
        is not None
    )


def _default_onboarding_state():
    return {
        "owner": {},
        "workspace": {},
        "shop": {},
        "team": {},
    }


def _get_onboarding_state():
    raw_state = session.get(ONBOARDING_SESSION_KEY) or {}
    state = _default_onboarding_state()

    for key in state:
        if isinstance(raw_state.get(key), dict):
            state[key].update(raw_state[key])

    return state


def _save_onboarding_state(state) -> None:
    session[ONBOARDING_SESSION_KEY] = {
        "owner": dict(state.get("owner") or {}),
        "workspace": dict(state.get("workspace") or {}),
        "shop": dict(state.get("shop") or {}),
        "team": dict(state.get("team") or {}),
    }
    session.modified = True


def _clear_onboarding_state() -> None:
    session.pop(ONBOARDING_SESSION_KEY, None)
    session.modified = True


def _onboarding_step_url(step: str) -> str:
    if step == "account":
        return url_for("public.start_workspace")
    return url_for("public.start_workspace", step=step)


def _validate_onboarding_step(step: str) -> str:
    clean_step = str(step or "account").strip().lower()
    if clean_step not in ONBOARDING_STEPS:
        abort(404)
    return clean_step


def _required_onboarding_step(step: str, state) -> str | None:
    owner_ready = bool(state["owner"].get("login_username") and state["owner"].get("password_hash"))
    owner_verified = _owner_is_verified(state)
    workspace_ready = bool(state["workspace"].get("name"))

    if step in {"verify", "workspace", "shop", "team", "review"} and not owner_ready:
        return "account"

    if step in {"workspace", "shop", "team", "review"} and not owner_verified:
        return "verify"

    if step in {"shop", "team", "review"} and not workspace_ready:
        return "workspace"

    return None


def _build_onboarding_steps(current_step: str):
    labels = {
        "account": "Owner account",
        "verify": "Verify",
        "workspace": "Workspace",
        "shop": "First shop",
        "team": "First team",
        "review": "Review",
    }
    current_index = ONBOARDING_STEPS.index(current_step)
    items = []

    for index, step in enumerate(ONBOARDING_STEPS):
        items.append(
            {
                "key": step,
                "label": labels[step],
                "href": _onboarding_step_url(step),
                "state": (
                    "current"
                    if step == current_step
                    else "done"
                    if index < current_index
                    else "upcoming"
                ),
            }
        )

    return items


def _state_identifier_taken(state, username: str, phone: str | None, *, ignore_section: str | None = None) -> bool:
    normalized_username = normalize_username(username)
    normalized_phone = normalize_phone(phone)

    for section_name in ("owner", "team"):
        if section_name == ignore_section:
            continue

        section = state.get(section_name) or {}
        existing_username = normalize_username(section.get("login_username"))
        existing_phone = normalize_phone(section.get("phone"))

        if normalized_username and existing_username and existing_username.lower() == normalized_username.lower():
            return True

        if normalized_phone and existing_phone and existing_phone == normalized_phone:
            return True

        if normalized_username and existing_phone and normalize_phone(normalized_username) == existing_phone:
            return True

        if normalized_phone and existing_username and existing_username.lower() == normalized_phone.lower():
            return True

    return False


def _build_onboarding_review_items(state):
    owner = state.get("owner") or {}
    workspace = state.get("workspace") or {}
    shop = state.get("shop") or {}
    team = state.get("team") or {}
    owner_verified = _owner_is_verified(state)

    return [
        {
            "label": "Owner account ready",
            "done": bool(owner.get("full_name") and owner.get("login_username")),
            "summary": owner.get("full_name") or "Add the workspace owner account.",
        },
        {
            "label": "Telegram verified",
            "done": owner_verified,
            "summary": (
                "Telegram contact confirmed for the owner account."
                if owner_verified
                else "Open the bot and press Start before launching the workspace."
            ),
        },
        {
            "label": "Workspace profile added",
            "done": bool(workspace.get("name")),
            "summary": workspace.get("name") or "Add the registered business name and identity.",
        },
        {
            "label": "First shop linked",
            "done": bool(shop.get("name")),
            "summary": shop.get("name") or "Optional. Add a first branch if the business already operates one.",
        },
        {
            "label": "First teammate prepared",
            "done": bool(team.get("full_name")),
            "summary": team.get("full_name") or "Optional. Add one more team member now or do it later from Workspace.",
        },
    ]


def _persist_onboarding_workspace(state):
    owner_state = state.get("owner") or {}
    workspace_state = state.get("workspace") or {}
    shop_state = state.get("shop") or {}
    team_state = state.get("team") or {}
    verification = _owner_verification_record(state)

    owner_username = owner_state.get("login_username") or ""
    owner_phone = normalize_phone(owner_state.get("phone"))
    team_username = team_state.get("login_username") or ""
    team_phone = normalize_phone(team_state.get("phone"))

    if not owner_username or not owner_state.get("password_hash"):
        raise ValueError("Owner account details are incomplete.")

    if not (verification and verification.is_verified()):
        raise ValueError("Verify the owner account in Telegram before launching the workspace.")

    if _username_taken(owner_username) or _phone_taken(owner_phone):
        raise ValueError("The owner login details are already in use.")

    if team_state.get("full_name"):
        if not team_username or not team_state.get("password_hash"):
            raise ValueError("The teammate account is incomplete.")
        if _username_taken(team_username) or _phone_taken(team_phone):
            raise ValueError("The teammate login details are already in use.")

    factory = Factory(
        name=(workspace_state.get("name") or "").strip(),
        owner_name=(workspace_state.get("owner_name") or "").strip() or None,
        location=(workspace_state.get("location") or "").strip() or None,
        phone=(workspace_state.get("phone") or "").strip() or None,
        note=(workspace_state.get("note") or "").strip() or None,
    )
    db.session.add(factory)
    db.session.flush()

    owner = User(
        username=owner_username,
        full_name=(owner_state.get("full_name") or "").strip() or None,
        phone=owner_phone,
        role="admin",
        factory_id=factory.id,
        password_changed_at=datetime.utcnow(),
    )
    owner.password_hash = owner_state["password_hash"]
    db.session.add(owner)
    db.session.flush()
    factory.owner_user_id = owner.id

    if verification and verification.telegram_chat_id:
        existing_chat_link = TelegramLink.query.filter_by(
            telegram_chat_id=verification.telegram_chat_id
        ).first()
        if not existing_chat_link:
            db.session.add(
                TelegramLink(
                    telegram_chat_id=verification.telegram_chat_id,
                    user_id=owner.id,
                    factory_id=factory.id,
                )
            )

    created_shop = None
    if (shop_state.get("name") or "").strip():
        created_shop = Shop(
            factory_id=factory.id,
            name=(shop_state.get("name") or "").strip(),
            location=(shop_state.get("location") or "").strip() or None,
            note=(shop_state.get("note") or "").strip() or None,
            is_active=True,
        )
        db.session.add(created_shop)
        db.session.flush()
        db.session.add(
            ShopFactoryLink(
                shop_id=created_shop.id,
                factory_id=factory.id,
            )
        )

    if (team_state.get("full_name") or "").strip():
        teammate_role = (team_state.get("role") or "manager").strip()
        teammate_shop_id = None
        if teammate_role == "shop" and created_shop and team_state.get("shop_target") == "first":
            teammate_shop_id = created_shop.id

        teammate = User(
            username=team_username,
            full_name=(team_state.get("full_name") or "").strip() or None,
            phone=team_phone,
            role=teammate_role,
            factory_id=factory.id,
            shop_id=teammate_shop_id,
            must_change_password=True,
            password_changed_at=datetime.utcnow(),
        )
        teammate.password_hash = team_state["password_hash"]
        db.session.add(teammate)

    db.session.commit()
    return factory, owner


def _home_stats():
    return {
        "workspace_count": Factory.query.count(),
        "team_count": User.query.count(),
        "shop_count": Shop.query.count(),
    }


@public_bp.route("/uploads/<path:filename>")
def uploaded_file(filename: str):
    filename = (filename or "").strip().lstrip("/")
    if not filename:
        abort(404)

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)
    return send_from_directory(upload_folder, filename)


# ======================
#   🏠 HOME
# ======================
@public_bp.route("/")
def home():
    stats = _home_stats()
    feature_cards = [
        {
            "title": translate("home_feature_1_title"),
            "body": translate("home_feature_1_body"),
        },
        {
            "title": translate("home_feature_2_title"),
            "body": translate("home_feature_2_body"),
        },
        {
            "title": translate("home_feature_3_title"),
            "body": translate("home_feature_3_body"),
        },
        {
            "title": translate("home_feature_4_title"),
            "body": translate("home_feature_4_body"),
        },
    ]
    role_cards = [
        {
            "title": translate("home_role_1_title"),
            "body": translate("home_role_1_body"),
        },
        {
            "title": translate("home_role_2_title"),
            "body": translate("home_role_2_body"),
        },
        {
            "title": translate("home_role_3_title"),
            "body": translate("home_role_3_body"),
        },
        {
            "title": translate("home_role_4_title"),
            "body": translate("home_role_4_body"),
        },
    ]
    launch_steps = [
        translate("home_launch_step_1"),
        translate("home_launch_step_2"),
        translate("home_launch_step_3"),
        translate("home_launch_step_4"),
        translate("home_launch_step_5"),
        translate("home_launch_step_6"),
    ]

    return render_template(
        "public/home.html",
        home_stats=stats,
        feature_cards=feature_cards,
        role_cards=role_cards,
        launch_steps=launch_steps,
        public_phone=_public_phone(),
        public_phone_href=_public_phone_href(),
        public_telegram_url=_telegram_url(),
    )


@public_bp.route("/start-workspace", methods=["GET", "POST"])
@public_bp.route("/start-workspace/<step>", methods=["GET", "POST"])
def start_workspace(step="account"):
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    current_step = _validate_onboarding_step(step)
    state = _get_onboarding_state()
    redirect_step = _required_onboarding_step(current_step, state)
    if redirect_step:
        return redirect(_onboarding_step_url(redirect_step))

    owner_state = state.get("owner") or {}
    workspace_state = state.get("workspace") or {}
    shop_state = state.get("shop") or {}
    team_state = state.get("team") or {}

    step_meta = {
        "account": {
            "kicker": "Step 1",
            "title": "Create the owner account",
            "subtitle": "This first account becomes the workspace owner. Start with a clean phone number so login feels easy and Telegram verification works on the next step.",
        },
        "verify": {
            "kicker": "Step 2",
            "title": "Verify the owner in Telegram",
            "subtitle": "Open the Adras bot, press Start, and come back here. That keeps the signup flow lightweight while still confirming the owner contact before the workspace is created.",
        },
        "workspace": {
            "kicker": "Step 3",
            "title": "Register the business workspace",
            "subtitle": "Give the business a clean identity so the dashboard, people, and future reports all point to the right workspace.",
        },
        "shop": {
            "kicker": "Step 4",
            "title": "Add the first shop",
            "subtitle": "Optional for now. If you already have a branch or store, link it here so stock and shop users have a home.",
        },
        "team": {
            "kicker": "Step 5",
            "title": "Prepare the first teammate",
            "subtitle": "Optional for now. Add one more person now, or finish setup and handle staff from the workspace page later.",
        },
        "review": {
            "kicker": "Step 6",
            "title": "Review and launch",
            "subtitle": "This is the first owner view I would want before going live: who owns the workspace, what business is being created, and what still needs attention after launch.",
        },
    }

    prev_step = None
    current_index = ONBOARDING_STEPS.index(current_step)
    if current_index > 0:
        prev_step = ONBOARDING_STEPS[current_index - 1]

    if current_step == "account":
        form = OnboardingOwnerForm()
        if request.method == "GET":
            phone_country_code, phone_number = _split_owner_phone_parts(owner_state.get("phone"))
            form.full_name.data = owner_state.get("full_name")
            form.phone_country_code.data = owner_state.get("phone_country_code") or phone_country_code or "+998"
            form.phone_number.data = owner_state.get("phone_number") or phone_number
            form.username.data = owner_state.get("username")
            form.language.data = owner_state.get("language") or session.get("lang_code") or "en"

        if form.submit_owner.data:
            if form.validate_on_submit():
                full_name = (form.full_name.data or "").strip()
                phone_country_code = (form.phone_country_code.data or "+998").strip()
                phone_number = (form.phone_number.data or "").strip()
                phone = normalize_phone(f"{phone_country_code}{phone_number}")
                username_input = (form.username.data or "").strip()
                login_username = build_login_username(username_input, phone)
                selected_language = (form.language.data or "en").strip().lower()

                if not phone:
                    flash("Enter a valid phone number for the owner account.", "danger")
                elif not login_username:
                    flash("Enter a username or a phone number for the owner account.", "danger")
                elif _username_taken(login_username):
                    flash("That username is already in use.", "danger")
                elif _phone_taken(phone):
                    flash("That phone number is already in use.", "danger")
                else:
                    state["owner"] = {
                        "full_name": full_name,
                        "phone": phone,
                        "phone_country_code": phone_country_code,
                        "phone_number": phone_number,
                        "username": username_input,
                        "login_username": login_username,
                        "password_hash": generate_password_hash(form.password.data or ""),
                        "language": selected_language,
                    }
                    _save_onboarding_state(state)
                    _ensure_owner_verification(state)
                    session["lang"] = selected_language
                    session["lang_code"] = selected_language
                    refresh()
                    return redirect(_onboarding_step_url("verify"))
            elif request.method == "POST":
                flash("Please review the owner account fields and try again.", "danger")

        return render_template(
            "public/onboarding.html",
            form=form,
            step_key=current_step,
            step_meta=step_meta[current_step],
            onboarding_steps=_build_onboarding_steps(current_step),
            prev_step=prev_step,
            public_phone=_public_phone(),
            public_phone_href=_public_phone_href(),
            public_telegram_url=_telegram_url(),
            public_telegram_bot_url=_telegram_bot_url(),
        )

    if current_step == "verify":
        form = OnboardingVerifyForm()
        verification = _ensure_owner_verification(state)
        is_verified = bool(verification and verification.is_verified())

        if form.submit_verify.data and form.validate_on_submit():
            if not is_verified:
                flash("Open the Telegram bot, press Start there, then come back and continue.", "danger")
            else:
                return redirect(_onboarding_step_url("workspace"))

        return render_template(
            "public/onboarding.html",
            form=form,
            step_key=current_step,
            step_meta=step_meta[current_step],
            onboarding_steps=_build_onboarding_steps(current_step),
            prev_step=prev_step,
            owner_state=owner_state,
            telegram_verify_record=verification,
            telegram_verify_ready=is_verified,
            telegram_verify_url=_telegram_signup_url(getattr(verification, "token", None)),
            public_phone=_public_phone(),
            public_phone_href=_public_phone_href(),
            public_telegram_url=_telegram_url(),
            public_telegram_bot_url=_telegram_bot_url(),
        )

    if current_step == "workspace":
        form = OnboardingWorkspaceForm()
        if request.method == "GET":
            form.name.data = workspace_state.get("name")
            form.owner_name.data = workspace_state.get("owner_name") or owner_state.get("full_name")
            form.location.data = workspace_state.get("location")
            form.phone.data = workspace_state.get("phone") or owner_state.get("phone")
            form.note.data = workspace_state.get("note")

        if form.submit_workspace_setup.data:
            if form.validate_on_submit():
                state["workspace"] = {
                    "name": (form.name.data or "").strip(),
                    "owner_name": (form.owner_name.data or "").strip() or None,
                    "location": (form.location.data or "").strip() or None,
                    "phone": (form.phone.data or "").strip() or None,
                    "note": (form.note.data or "").strip() or None,
                }
                _save_onboarding_state(state)
                return redirect(_onboarding_step_url("shop"))
            elif request.method == "POST":
                flash("Please review the workspace details and try again.", "danger")

        return render_template(
            "public/onboarding.html",
            form=form,
            step_key=current_step,
            step_meta=step_meta[current_step],
            onboarding_steps=_build_onboarding_steps(current_step),
            prev_step=prev_step,
            public_phone=_public_phone(),
            public_phone_href=_public_phone_href(),
            public_telegram_url=_telegram_url(),
            public_telegram_bot_url=_telegram_bot_url(),
        )

    if current_step == "shop":
        form = OnboardingShopForm()
        if request.method == "GET":
            form.name.data = shop_state.get("name")
            form.location.data = shop_state.get("location")
            form.note.data = shop_state.get("note")

        if form.submit_shop.data:
            if form.validate_on_submit():
                shop_name = (form.name.data or "").strip()
                state["shop"] = {
                    "name": shop_name or None,
                    "location": (form.location.data or "").strip() or None,
                    "note": (form.note.data or "").strip() or None,
                }
                _save_onboarding_state(state)
                return redirect(_onboarding_step_url("team"))
            elif request.method == "POST":
                flash("Please review the shop details and try again.", "danger")

        return render_template(
            "public/onboarding.html",
            form=form,
            step_key=current_step,
            step_meta=step_meta[current_step],
            onboarding_steps=_build_onboarding_steps(current_step),
            prev_step=prev_step,
            public_phone=_public_phone(),
            public_phone_href=_public_phone_href(),
            public_telegram_url=_telegram_url(),
            public_telegram_bot_url=_telegram_bot_url(),
        )

    if current_step == "team":
        form = OnboardingTeamForm()
        if shop_state.get("name"):
            form.shop_target.choices = [
                ("none", "No shop"),
                ("first", f"First shop: {shop_state['name']}"),
            ]
        else:
            form.shop_target.choices = [("none", "No shop available yet")]

        if request.method == "GET":
            form.full_name.data = team_state.get("full_name")
            form.phone.data = team_state.get("phone")
            form.username.data = team_state.get("username")
            form.role.data = team_state.get("role") or "manager"
            form.shop_target.data = team_state.get("shop_target") or "none"

        if form.submit_team.data:
            if form.validate_on_submit():
                full_name = (form.full_name.data or "").strip()
                phone = normalize_phone(form.phone.data)
                username_input = (form.username.data or "").strip()
                password = form.password.data or ""
                role = (form.role.data or "manager").strip()
                shop_target = (form.shop_target.data or "none").strip()
                has_team_data = bool(full_name or phone or username_input or password)

                if not has_team_data:
                    state["team"] = {}
                    _save_onboarding_state(state)
                    return redirect(_onboarding_step_url("review"))

                login_username = build_login_username(username_input, phone)

                if not full_name:
                    flash("Add the teammate full name or leave the whole step empty to skip it.", "danger")
                elif not password:
                    flash("Add a password for the teammate account.", "danger")
                elif not login_username:
                    flash("Add a username or phone number for the teammate account.", "danger")
                elif _state_identifier_taken(state, login_username, phone, ignore_section="team"):
                    flash("That teammate login conflicts with another account in this setup flow.", "danger")
                elif _username_taken(login_username):
                    flash("That teammate username is already in use.", "danger")
                elif _phone_taken(phone):
                    flash("That teammate phone number is already in use.", "danger")
                elif role == "shop" and not shop_state.get("name"):
                    flash("Create the first shop before assigning a shop role in onboarding.", "danger")
                else:
                    state["team"] = {
                        "full_name": full_name,
                        "phone": phone,
                        "username": username_input,
                        "login_username": login_username,
                        "password_hash": generate_password_hash(password),
                        "role": role,
                        "shop_target": shop_target,
                    }
                    _save_onboarding_state(state)
                    return redirect(_onboarding_step_url("review"))
            elif request.method == "POST":
                flash("Please review the teammate fields and try again.", "danger")

        return render_template(
            "public/onboarding.html",
            form=form,
            step_key=current_step,
            step_meta=step_meta[current_step],
            onboarding_steps=_build_onboarding_steps(current_step),
            prev_step=prev_step,
            public_phone=_public_phone(),
            public_phone_href=_public_phone_href(),
            public_telegram_url=_telegram_url(),
            public_telegram_bot_url=_telegram_bot_url(),
        )

    launch_form = OnboardingLaunchForm()
    review_items = _build_onboarding_review_items(state)

    if launch_form.submit_launch.data and launch_form.validate_on_submit():
        try:
            factory, owner = _persist_onboarding_workspace(state)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(_onboarding_step_url("account"))

        login_user(owner, remember=True)
        session.permanent = True
        session["factory_id"] = factory.id

        selected_language = owner_state.get("language")
        if selected_language:
            session["lang"] = selected_language
            session["lang_code"] = selected_language
            refresh()

        _clear_onboarding_state()
        flash("Workspace created successfully. Finish the remaining setup from the dashboard and workspace page.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template(
        "public/onboarding.html",
        form=launch_form,
        step_key=current_step,
        step_meta=step_meta[current_step],
        onboarding_steps=_build_onboarding_steps(current_step),
        prev_step=prev_step,
        review_items=review_items,
        owner_state=owner_state,
        owner_verified=_owner_is_verified(state),
        workspace_state=workspace_state,
        shop_state=shop_state,
        team_state=team_state,
        public_phone=_public_phone(),
        public_phone_href=_public_phone_href(),
        public_telegram_url=_telegram_url(),
        public_telegram_bot_url=_telegram_bot_url(),
    )


# ======================
#   📦 CATALOG
# ======================
@public_bp.route("/catalog")
def catalog():
    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()

    if not _product_column_exists("is_published"):
        return render_template(
            "public/catalog.html",
            products=[],
            categories=[],
            q=q,
            selected_category=category,
            public_telegram_url=_telegram_url(),
            tg_order_link=_tg_order_link,
        )

    base_q = Product.query.filter(Product.is_published.is_(True))

    categories_rows = (
        Product.query
        .with_entities(Product.category)
        .filter(Product.is_published.is_(True))
        .filter(Product.category.isnot(None))
        .filter(Product.category != "")
        .distinct()
        .order_by(Product.category.asc())
        .all()
    )
    categories = [r[0] for r in categories_rows if r and r[0]]

    if category:
        base_q = base_q.filter(Product.category == category)

    if q:
        like = f"%{q}%"
        base_q = base_q.filter(
            or_(
                Product.name.ilike(like),
                Product.category.ilike(like),
            )
        )

    products = base_q.order_by(Product.id.desc()).all()

    return render_template(
        "public/catalog.html",
        products=products,
        categories=categories,
        q=q,
        selected_category=category,
        public_telegram_url=_telegram_url(),
        tg_order_link=_tg_order_link,
    )


# ======================
#   👕 PRODUCT DETAIL
# ======================
@public_bp.route("/p/<int:product_id>")
def product_detail(product_id: int):
    if not _product_column_exists("is_published"):
        abort(404)

    product = Product.query.filter(
        Product.id == product_id,
        Product.is_published.is_(True),
    ).first()

    if not product:
        abort(404)

    return render_template(
        "public/product_detail.html",
        product=product,
        garment_analysis=garment_analysis_service.build_view_model(product),
        public_telegram_url=_telegram_url(),
        tg_order_link=_tg_order_link,
    )


# ======================
#   ☎️ CONTACT
# ======================
@public_bp.route("/contact")
def contact():
    return render_template(
        "public/contact.html",
        public_telegram_url=_telegram_url(),
        tg_order_link=_tg_order_link,
    )
