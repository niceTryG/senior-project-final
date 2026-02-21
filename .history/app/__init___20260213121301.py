from flask import Flask, session, redirect, url_for, request
from datetime import datetime

from .extensions import db, login_manager
from .translations import t as translate
from .models import User, Factory   # ← added Factory
from .services.currency_service import get_usd_uzs_rate  # (optional, still ok to keep)


def create_app(config_class="config.DevConfig"):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # init extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"          # redirect anonymous to login
    login_manager.login_message_category = "warning"

    # ---------------------------------------
    # Create default factory + users
    # ---------------------------------------
    def create_default_users(default_factory: Factory):
        """
        Create Dad / Mum / Uncle only if they don't exist.
        If they exist but have no factory_id, attach them to default_factory.
        """
        default_users = [
            ("Muzaffarrano", "manager", "Muhammadyusuf2024"),   # Dad
            ("Ranomuzaffar", "accountant", "Muhlisarano"),      # Mum
            ("Doniyor701", "shop", "Umarbek"),                  # Uncle (shop)
        ]

        for username, role, password in default_users:
            user = User.query.filter_by(username=username).first()
            if not user:
                user = User(username=username, role=role, factory_id=default_factory.id)
                user.set_password(password)
                db.session.add(user)
            else:
                # if user exists but has no factory yet – attach to default
                if user.factory_id is None:
                    user.factory_id = default_factory.id

        db.session.commit()

    # create tables + default factory + default users
    with app.app_context():
        db.create_all()

        # --- create or get default factory ---
        default_factory = Factory.query.first()
        if not default_factory:
            default_factory = Factory(
                name="Mini Moda Factory",
                owner_name="Muzaffar",
                note="Default factory for family users",
            )
            db.session.add(default_factory)
            db.session.commit()
            print("Created default Factory: Mini Moda Factory")

        # --- admin user (you) ---
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            admin = User(
                username="admin",
                role="admin",
                factory_id=default_factory.id,  # attach to same factory for now
            )
            admin.set_password("Musakh")
            db.session.add(admin)
            db.session.commit()
            print("Created default user: admin / Musakh")
        else:
            # if admin exists but has no factory, attach to default
            if admin.factory_id is None:
                admin.factory_id = default_factory.id
                db.session.commit()

        # --- dad, mum, uncle ---
        create_default_users(default_factory)

    # login manager user loader
    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except (TypeError, ValueError):
            return None

    # inject translation helper and current_lang into templates
    @app.context_processor
    def inject_globals():
        def _t(key: str) -> str:
            lang = session.get("lang", "ru")
            return translate(key, lang)

        def current_lang() -> str:
            return session.get("lang", "ru")

        def format_money(amount, currency):
            if amount is None:
                return ""
            try:
                value = float(amount)
            except (TypeError, ValueError):
                return ""

            if currency == "UZS":
                return f"{int(round(value)):,} сум".replace(",", " ")
            if currency == "USD":
                return f"${value:,.2f}"
            return str(value)

        LOW_STOCK_THRESHOLD = 5

        return {
            "t": _t,
            "current_lang": current_lang,
            "format_money": format_money,
            "LOW_STOCK_THRESHOLD": LOW_STOCK_THRESHOLD,
            "current_year": datetime.utcnow().year,
        }

    # language switch route
    @app.route("/lang/<lang_code>")
    def switch_language(lang_code):
        if lang_code not in ("ru", "uz"):
            lang_code = "ru"
        # keep both keys so code using lang / lang_code works
        session["lang"] = lang_code
        session["lang_code"] = lang_code

        ref = request.referrer
        if ref:
            return redirect(ref)
        return redirect(url_for("main.dashboard"))

    # ---- register blueprints ----
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
