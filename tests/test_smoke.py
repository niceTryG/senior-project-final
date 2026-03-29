import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

from app import create_app
from app.db_migrations import upgrade_database
from app.extensions import db


class SmokeTestCase(unittest.TestCase):
    def setUp(self):
        base_tmp_dir = Path(__file__).resolve().parents[1] / ".tmp_test"
        base_tmp_dir.mkdir(exist_ok=True)
        fd, raw_path = tempfile.mkstemp(dir=base_tmp_dir, suffix=".db")
        os.close(fd)
        Path(raw_path).unlink(missing_ok=True)
        self.db_path = Path(raw_path).resolve()
        db_uri = f"sqlite:///{self.db_path}"

        class TestConfig:
            DEBUG = True
            TESTING = True
            SECRET_KEY = "test-secret-key"
            SQLALCHEMY_DATABASE_URI = db_uri
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
            UPLOAD_FOLDER = "app/static/uploads/products"
            ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
            MAX_CONTENT_LENGTH = 5 * 1024 * 1024
            SESSION_COOKIE_HTTPONLY = True
            SESSION_COOKIE_SAMESITE = "Lax"
            SESSION_COOKIE_SECURE = False
            REMEMBER_COOKIE_SECURE = False
            REMEMBER_COOKIE_HTTPONLY = True
            AUTO_DB_BOOTSTRAP = True
            PROD_ALLOW_SQLITE = True
            PUBLIC_TELEGRAM_URL = "https://t.me/minimoda_sklad_bot"

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.db_path.unlink(missing_ok=True)

    def test_public_pages_render(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_protected_profile_redirects_to_login(self):
        response = self.client.get("/profile", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_schema_migrations_are_recorded(self):
        with self.app.app_context():
            rows = db.session.execute(
                text("SELECT version FROM schema_migrations ORDER BY version")
            ).fetchall()
        versions = [version for (version,) in rows]
        self.assertEqual(versions, ["0001", "0002", "0003", "0004"])

    def test_migration_status_command(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=["migration-status"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("0001 [applied] create base schema", result.output)

    def test_alembic_scaffolding_files_exist(self):
        project_root = Path(__file__).resolve().parents[1]
        expected_paths = [
            project_root / "migrations" / "alembic.ini",
            project_root / "migrations" / "env.py",
            project_root / "migrations" / "script.py.mako",
            project_root / "migrations" / "versions" / "20260329_0001_baseline_schema.py",
        ]
        for path in expected_paths:
            self.assertTrue(path.exists(), f"Missing migration scaffold: {path}")


class ProductionConfigGuardTestCase(unittest.TestCase):
    def test_production_requires_secret_key(self):
        class UnsafeProdConfig:
            DEBUG = False
            TESTING = True
            SECRET_KEY = "dev-only-change-me"
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            AUTO_DB_BOOTSTRAP = False
            PROD_ALLOW_SQLITE = True
            SESSION_COOKIE_HTTPONLY = True
            SESSION_COOKIE_SAMESITE = "Lax"
            SESSION_COOKIE_SECURE = True
            REMEMBER_COOKIE_SECURE = True
            REMEMBER_COOKIE_HTTPONLY = True
            PUBLIC_TELEGRAM_URL = "https://t.me/minimoda_sklad_bot"

        with self.assertRaisesRegex(RuntimeError, "SECRET_KEY"):
            create_app(UnsafeProdConfig)


class DeployPreflightCommandTestCase(unittest.TestCase):
    def setUp(self):
        base_tmp_dir = Path(__file__).resolve().parents[1] / ".tmp_test"
        base_tmp_dir.mkdir(exist_ok=True)
        fd, raw_path = tempfile.mkstemp(dir=base_tmp_dir, suffix=".db")
        os.close(fd)
        Path(raw_path).unlink(missing_ok=True)
        self.db_path = Path(raw_path).resolve()
        self.old_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")

    def tearDown(self):
        if self.old_bot_token is None:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        else:
            os.environ["TELEGRAM_BOT_TOKEN"] = self.old_bot_token
        self.db_path.unlink(missing_ok=True)

    def _make_prod_like_app(self, *, bootstrap: bool):
        db_uri = f"sqlite:///{self.db_path}"

        class ProdLikeConfig:
            DEBUG = False
            TESTING = False
            SECRET_KEY = "test-prod-secret"
            SQLALCHEMY_DATABASE_URI = db_uri
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
            UPLOAD_FOLDER = "app/static/uploads/products"
            ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
            MAX_CONTENT_LENGTH = 5 * 1024 * 1024
            SESSION_COOKIE_HTTPONLY = True
            SESSION_COOKIE_SAMESITE = "Lax"
            SESSION_COOKIE_SECURE = True
            REMEMBER_COOKIE_SECURE = True
            REMEMBER_COOKIE_HTTPONLY = True
            AUTO_DB_BOOTSTRAP = bootstrap
            PROD_ALLOW_SQLITE = True
            PUBLIC_TELEGRAM_URL = "https://t.me/minimoda_sklad_bot"

        return create_app(ProdLikeConfig)

    def test_deploy_preflight_passes_for_safe_config(self):
        os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot-token"
        app = self._make_prod_like_app(bootstrap=False)

        with app.app_context():
            upgrade_database(log=False)

        runner = app.test_cli_runner()
        result = runner.invoke(args=["deploy-preflight"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Deployment preflight passed.", result.output)
        self.assertIn("WARN: Deployment is using SQLite because PROD_ALLOW_SQLITE=1.", result.output)
        if importlib.util.find_spec("flask_migrate") is None:
            self.assertIn("Flask-Migrate/Alembic is not installed", result.output)

        with app.app_context():
            db.session.remove()
            db.engine.dispose()

    def test_deploy_preflight_fails_without_bot_token(self):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        app = self._make_prod_like_app(bootstrap=False)

        with app.app_context():
            upgrade_database(log=False)

        runner = app.test_cli_runner()
        result = runner.invoke(args=["deploy-preflight"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("TELEGRAM_BOT_TOKEN is not set.", result.output)

        with app.app_context():
            db.session.remove()
            db.engine.dispose()

    def test_deploy_preflight_fails_when_migrations_are_pending(self):
        os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot-token"
        app = self._make_prod_like_app(bootstrap=False)

        runner = app.test_cli_runner()
        result = runner.invoke(args=["deploy-preflight"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Pending database migrations detected", result.output)

        with app.app_context():
            db.session.remove()
            db.engine.dispose()
