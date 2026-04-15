import os
from pathlib import Path

from flask import Flask, session, redirect, url_for, request
from datetime import datetime, timezone
from flask_login import current_user
from flask.cli import with_appcontext
from jinja2 import Undefined
from flask_babel import refresh, get_locale
import click

from app.extensions import MIGRATE_AVAILABLE, babel
from app.i18n import select_locale, DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from .extensions import db, login_manager, migrate
from .translations import t as translate
from .models import User
from .db_migrations import migration_status, pending_migrations, upgrade_database
from .user_display import (
    display_value,
    get_user_display_name,
    get_user_initials,
    get_workspace_name,
)


def _validate_runtime_config(app: Flask) -> None:
    if app.debug:
        return

    secret_key = app.config.get("SECRET_KEY")
    if not secret_key or secret_key == "dev-only-change-me":
        raise RuntimeError("SECRET_KEY must be set for production.")

    db_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    if db_uri.startswith("sqlite:///") and not app.config.get("PROD_ALLOW_SQLITE", False):
        raise RuntimeError(
            "Production config is using SQLite. Set DATABASE_URL or PROD_ALLOW_SQLITE=1."
        )


def _bootstrap_database() -> None:
    upgrade_database()


def _deployment_preflight(app: Flask, *, require_bot: bool = True) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if app.debug:
        errors.append("DEBUG must be False for deployment.")

    if app.testing:
        errors.append("TESTING must be False for deployment.")

    secret_key = app.config.get("SECRET_KEY")
    if not secret_key or secret_key == "dev-only-change-me":
        errors.append("SECRET_KEY must be set to a strong non-default value.")

    if not app.config.get("SESSION_COOKIE_SECURE", False):
        errors.append("SESSION_COOKIE_SECURE must be enabled.")

    if not app.config.get("REMEMBER_COOKIE_SECURE", False):
        errors.append("REMEMBER_COOKIE_SECURE must be enabled.")

    if not app.config.get("SESSION_COOKIE_HTTPONLY", False):
        errors.append("SESSION_COOKIE_HTTPONLY must be enabled.")

    if not app.config.get("REMEMBER_COOKIE_HTTPONLY", False):
        errors.append("REMEMBER_COOKIE_HTTPONLY must be enabled.")

    same_site = str(app.config.get("SESSION_COOKIE_SAMESITE") or "").strip()
    if same_site not in {"Lax", "Strict", "None"}:
        errors.append("SESSION_COOKIE_SAMESITE must be one of Lax, Strict, or None.")
    elif same_site == "None":
        warnings.append("SESSION_COOKIE_SAMESITE=None is less strict; use Lax unless cross-site flows require it.")

    if app.config.get("AUTO_DB_BOOTSTRAP", False):
        errors.append("AUTO_DB_BOOTSTRAP must be disabled for deployment.")

    db_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    if db_uri.startswith("sqlite:///"):
        if app.config.get("PROD_ALLOW_SQLITE", False):
            warnings.append("Deployment is using SQLite because PROD_ALLOW_SQLITE=1.")
        else:
            errors.append("DATABASE_URL must point to PostgreSQL/MySQL, or explicitly allow SQLite.")

    upload_folder = Path(str(app.config.get("UPLOAD_FOLDER") or "")).expanduser()
    if not upload_folder.is_absolute():
        upload_folder = Path(app.root_path).parent / upload_folder
    if not upload_folder.exists():
        errors.append(f"UPLOAD_FOLDER does not exist: {upload_folder}")
    elif not upload_folder.is_dir():
        errors.append(f"UPLOAD_FOLDER is not a directory: {upload_folder}")

    pending = pending_migrations()
    if pending:
        pending_versions = ", ".join(migration.version for migration in pending)
        errors.append(
            "Pending database migrations detected: "
            f"{pending_versions}. Run `flask --app wsgi db-upgrade` first."
        )

    migrations_dir = Path(app.root_path).parent / "migrations"
    if not migrations_dir.exists():
        warnings.append("Alembic migrations directory is missing; Flask-Migrate commands will not work.")
    elif not MIGRATE_AVAILABLE:
        warnings.append(
            "Flask-Migrate/Alembic is not installed in the current environment yet. "
            "Run `pip install -r requirements.txt` before using `flask db` commands."
        )

    if require_bot and not (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip():
        errors.append("TELEGRAM_BOT_TOKEN is not set.")

    return errors, warnings


def create_app(config_class="config.DevConfig"):
    app = Flask(__name__)
    app.config.from_object(config_class)
    _validate_runtime_config(app)

    # Babel config
    app.config["BABEL_DEFAULT_LOCALE"] = DEFAULT_LANGUAGE
    app.config["BABEL_TRANSLATION_DIRECTORIES"] = "translations"

    babel.init_app(app, locale_selector=select_locale)

    # -------------------------
    # Extensions
    # -------------------------
    db.init_app(app)
    if migrate is not None:
        migrate.init_app(app, db, compare_type=True, render_as_batch=True)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    # -------------------------
    # Create tables only
    # -------------------------
    if app.config.get("AUTO_DB_BOOTSTRAP", False):
        with app.app_context():
            _bootstrap_database()

    # -------------------------
    # Login manager
    # -------------------------
    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except (TypeError, ValueError):
            return None

    # -------------------------
    # GLOBAL LOGIN WALL
    # -------------------------
    @app.before_request
    def require_login():
        # Allow static assets
        if request.endpoint and request.endpoint.startswith("static"):
            return

        # Allow auth endpoints
        if request.endpoint in ("auth.login", "auth.logout", "auth.security_wall"):
            return

        # Allow language switch even before login
        if request.endpoint == "switch_language":
            return

        # Allow PUBLIC routes (no login required)
        if request.endpoint and request.endpoint.startswith("public."):
            return

        # Allow one-time setup URL even when not logged in
        if request.path.startswith("/setup/") or request.path.startswith("/auth/setup/"):
            return

        # Everything else requires authentication
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))

        if getattr(current_user, "must_change_password", False):
            if request.endpoint not in {"auth.security_wall", "auth.logout", "switch_language"}:
                return redirect(url_for("auth.security_wall"))

        # Superadmins operate across all tenants — no factory context needed
        if getattr(current_user, "is_superadmin", False):
            return

        # Auto-select a factory if none selected yet
        if "factory_id" not in session:
            from .models import Factory  # local import avoids circular imports

            first_factory = Factory.query.first()
            if first_factory:
                session["factory_id"] = first_factory.id
            elif app.config.get("AUTO_DB_BOOTSTRAP", False):
                # Create a default factory ONLY for admin users
                if getattr(current_user, "role", None) == "admin":
                    default_factory = Factory(name="Adras Factory")
                    db.session.add(default_factory)
                    db.session.commit()
                    session["factory_id"] = default_factory.id

    # -------------------------
    # CLI: Create Superadmin
    # -------------------------
    @app.cli.command("create-superadmin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @with_appcontext
    def create_superadmin(username, password):
        existing = User.query.filter_by(role="superadmin").first()
        if existing:
            click.echo("A superadmin already exists. Aborting.")
            return

        user = User(username=username, role="superadmin", factory_id=None, shop_id=None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        click.echo(f"Superadmin '{username}' created successfully.")

    # -------------------------
    # CLI: Create User
    # -------------------------
    @app.cli.command("create-user")
    @click.option("--username", prompt=True)
    @click.option("--role", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @with_appcontext
    def create_user(username, role, password):
        if User.query.filter_by(username=username).first():
            click.echo("User already exists.")
            return

        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        click.echo(f"User '{username}' created.")

    @app.cli.command("init-db")
    @with_appcontext
    def init_db_command():
        _bootstrap_database()
        click.echo("Database tables and patches applied.")

    @app.cli.command("migration-status")
    @with_appcontext
    def migration_status_command():
        for row in migration_status():
            click.echo(f"{row['version']} [{row['status']}] {row['description']}")

    @app.cli.command("db-upgrade")
    @with_appcontext
    def db_upgrade_command():
        applied = upgrade_database()
        if applied:
            click.echo("Applied migrations: " + ", ".join(applied))
        else:
            click.echo("No pending migrations.")

    @app.cli.command("deploy-preflight")
    @click.option("--require-bot/--no-require-bot", default=True, show_default=True)
    @with_appcontext
    def deploy_preflight_command(require_bot):
        errors, warnings = _deployment_preflight(app, require_bot=require_bot)

        for warning in warnings:
            click.echo(f"WARN: {warning}")

        if errors:
            for error in errors:
                click.echo(f"ERROR: {error}")
            raise click.ClickException("Deployment preflight failed.")

        click.echo("Deployment preflight passed.")

    # -------------------------
    # Template globals
    # -------------------------
    @app.context_processor
    def inject_globals():
        locale_obj = get_locale()
        lang = str(locale_obj) if locale_obj else DEFAULT_LANGUAGE

        def _t(key: str) -> str:
            return translate(key, lang)

        def format_money(value, currency="UZS"):
            try:
                if isinstance(value, Undefined) or value is None:
                    num = 0.0
                else:
                    num = float(value)
            except Exception:
                num = 0.0

            if abs(num - int(num)) < 1e-9:
                formatted = f"{int(num):,}"
            else:
                formatted = f"{num:,.2f}"

            formatted = formatted.replace(",", " ")
            return f"{formatted} {currency}".strip()

        def format_money_compact(value, currency="UZS"):
            try:
                if isinstance(value, Undefined) or value is None:
                    num = 0.0
                else:
                    num = float(value)
            except Exception:
                num = 0.0

            abs_num = abs(num)

            if currency == "UZS":
                if abs_num >= 1_000_000_000:
                    formatted = f"{num / 1_000_000_000:.1f}B"
                elif abs_num >= 1_000_000:
                    formatted = f"{num / 1_000_000:.1f}M"
                elif abs_num >= 1_000:
                    formatted = f"{num / 1_000:.0f}K"
                else:
                    if abs(num - int(num)) < 1e-9:
                        formatted = f"{int(num):,}"
                    else:
                        formatted = f"{num:,.2f}"
                    formatted = formatted.replace(",", " ")

                return f"{formatted} {currency}".strip()

            if abs(num - int(num)) < 1e-9:
                formatted = f"{int(num):,}"
            else:
                formatted = f"{num:,.2f}"

                formatted = formatted.replace(",", " ")
            return f"{formatted} {currency}".strip()

        def product_image_url(value):
            if isinstance(value, Undefined) or value is None:
                return None

            raw = str(value).strip()
            if not raw:
                return None

            lowered = raw.lower()
            if lowered.startswith(("http://", "https://")):
                return raw

            if raw.startswith("/uploads/"):
                filename = raw[len("/uploads/"):].lstrip("/")
                if not filename:
                    return None
                return url_for("public.uploaded_file", filename=filename)

            if raw.startswith("uploads/"):
                return url_for("static", filename=raw)

            if raw.startswith("/static/"):
                return raw

            if raw.startswith("/"):
                return raw

            return url_for("static", filename=f"uploads/products/{raw}")

        now_utc = datetime.now(timezone.utc)

        return {
            "t": _t,
            "_": _t,  # so both {{ t('key') }} and {{ _('key') }} work
            "current_lang": lang,
            "supported_languages": SUPPORTED_LANGUAGES,
            "current_year": now_utc.year,
            "current_date": now_utc.date(),
            "format_money": format_money,
            "format_money_compact": format_money_compact,
            "product_image_url": product_image_url,
            "display_value": display_value,
            "user_display_name": get_user_display_name,
            "user_initials": get_user_initials,
            "workspace_name": get_workspace_name,
        }

    # -------------------------
    # Language switch
    # -------------------------
    @app.route("/lang/<lang_code>")
    def switch_language(lang_code):
        if lang_code not in SUPPORTED_LANGUAGES:
            lang_code = DEFAULT_LANGUAGE

        session["lang"] = lang_code
        session["lang_code"] = lang_code

        # Babel caches locale selection, so refresh after changing session
        refresh()

        ref = request.referrer
        if ref:
            return redirect(ref)

        return redirect(url_for("main.dashboard"))

    # -------------------------
    # Register Blueprints
    # -------------------------
    from .routes.auth_routes import auth_bp
    from .routes.dashboard_routes import main_bp
    from .routes.fabric_routes import fabrics_bp, legacy_fabrics_bp
    from .routes.product_routes import products_bp
    from .routes.sale_routes import sales_bp
    from .routes.cash_routes import cash_bp
    from .routes.shop_routes import shop_bp
    from .routes.api_dashboard_routes import api_dashboard_bp
    from .routes.shop_report_routes import shop_report_bp
    from .routes.shop_monthly_routes import shop_monthly_bp
    from .routes.fabric_report_routes import fabric_report_bp
    from .routes.manager_report_routes import manager_report_bp
    from .routes.accountant_report_routes import accountant_report_bp
    from .routes.history_routes import history_bp
    from app.cost.routes import bp as cost_bp
    from .routes.factory_routes import factory_bp
    from .routes.factory_cutting_routes import cutting_bp
    from .routes.public_routes import public_bp
    from .routes.admin_routes import admin_bp
    from .routes.superadmin_routes import superadmin_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(superadmin_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(factory_bp)
    app.register_blueprint(cutting_bp)
    app.register_blueprint(cost_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(legacy_fabrics_bp)
    app.register_blueprint(fabrics_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(shop_bp)
    app.register_blueprint(cash_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(api_dashboard_bp)
    app.register_blueprint(shop_report_bp)
    app.register_blueprint(shop_monthly_bp)
    app.register_blueprint(fabric_report_bp)
    app.register_blueprint(manager_report_bp)
    app.register_blueprint(accountant_report_bp)

    return app
