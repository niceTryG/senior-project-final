import os

from app import create_app


config_class = os.environ.get("FLASK_CONFIG", "config.DevConfig")
app = create_app(config_class=config_class)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=app.debug,
    )
