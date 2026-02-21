import os
from app import create_app

# Optional: use FLASK_CONFIG env var, else default to production config
config_class = os.environ.get("FLASK_CONFIG", "config.ProdConfig")

app = create_app(config_class=config_class)