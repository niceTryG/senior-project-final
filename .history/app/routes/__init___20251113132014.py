from .routes.auth_routes import auth_bp
from .routes.dashboard_routes import main_bp
from .routes.fabric_routes import fabrics_bp

app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)
app.register_blueprint(fabrics_bp)
