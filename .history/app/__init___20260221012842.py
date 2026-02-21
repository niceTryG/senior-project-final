from flask import Flask, session, redirect, url_for, request
from datetime import datetime
from flask_login import current_user
from flask.cli import with_appcontext
import click

from .extensions import db, login_manager
from .translations import t as translate
from .models import User, Factory


def create_app(config_class="config.DevConfig"):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # -------------------------
    # Production-safe defaults
    # -------------------------
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")

    if not app.debug:
        app.config.setdefault("SESSION_COOKIE_SECURE", True)

    # -------------------------
    # Extensions
    # -------------------------
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    # -------------------------
    # Create tables only
    # -------------------------
    with app.app_context():
        db.create_all()

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
        allowed_routes = [
            "auth.login",
            "static",
        ]

        if request.endpoint is None:
            return

        if request.endpoint in allowed_routes:
            return

        if request.endpoint.startswith("static"):
            return

        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))

    # -------------------------
    # CLI: Create Superadmin
    # -------------------------
    @app.cli.command("create-superadmin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @with_appcontext
    def create_superadmin(username, password):
        """
        Create first superadmin.
        Only allowed if no admin exists.
        """
        existing_admin = User.query.filter_by(role="admin").first()
        if existing_admin:
            click.echo("An admin already exists. Aborting.")
            return

        user = User(username=username, role="admin")
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
        """
        Create additional users manually.
        """
        if User.query.filter_by(username=username).first():
            click.echo("User already exists.")
            return

        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        click.echo(f"User '{username}' created.")

    # -------------------------
    # Template globals
    # -------------------------
    @app.context_processor
    def inject_globals():
        def _t(key: str) -> str:
            lang = session.get("lang", "ru")
            return translate(key, lang)

        def current_lang() -> str:
            return session.get("lang", "ru")

        return {
            "t": _t,
            "current_lang": current_lang,
            "current_year": datetime.utcnow().year,
        }

    # -------------------------
    # Language switch
    # -------------------------
    @app.route("/lang/<lang_code>")
    def switch_language(lang_code):
        if lang_code not in ("ru", "uz"):
            lang_code = "ru"

        session["lang"] = lang_code
        session["lang_code"] = lang_code

        ref = request.referrer
        if ref:
            return redirect(ref)

        return redirect(url_for("main.dashboard"))

    # -------------------------
    # Register Blueprints
    # -------------------------
    from .routes.auth_routes import auth_bp
    from .routes.dashboard_routes import main_bp
    from .routes.fabric_routes import fabrics_bp
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

    app.register_blueprint(factory_bp)
    app.register_blueprint(cost_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
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