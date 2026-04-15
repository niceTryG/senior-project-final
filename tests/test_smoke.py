import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

from app import create_app
from app.db_migrations import MIGRATIONS, upgrade_database
from app.extensions import db
from app.models import Factory, Fabric, Product, ProductComposition
from app.services.garment_analysis_service import GarmentImageAnalysisService


class SmokeTestCase(unittest.TestCase):
    def setUp(self):
        base_tmp_dir = Path(__file__).resolve().parents[1] / ".tmp_test"
        base_tmp_dir.mkdir(exist_ok=True)
        self.temp_dir = Path(tempfile.mkdtemp(dir=base_tmp_dir)).resolve()
        self.db_path = (self.temp_dir / "test.db").resolve()
        db_uri = f"sqlite:///{self.db_path}"
        self.upload_dir = (self.temp_dir / "uploads").resolve()
        self.upload_dir.mkdir(parents=True, exist_ok=True)

        class TestConfig:
            DEBUG = True
            TESTING = True
            SECRET_KEY = "test-secret-key"
            SQLALCHEMY_DATABASE_URI = db_uri
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
            UPLOAD_FOLDER = str(self.upload_dir)
            ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
            MAX_CONTENT_LENGTH = 5 * 1024 * 1024
            SESSION_COOKIE_HTTPONLY = True
            SESSION_COOKIE_SAMESITE = "Lax"
            SESSION_COOKIE_SECURE = False
            REMEMBER_COOKIE_SECURE = False
            REMEMBER_COOKIE_HTTPONLY = True
            AUTO_DB_BOOTSTRAP = True
            PROD_ALLOW_SQLITE = True
            PUBLIC_TELEGRAM_URL = "https://t.me/adras_demo_bot"

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.client = None
        self.app = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

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
        self.assertEqual(versions, [migration.version for migration in MIGRATIONS])

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

    def test_garment_analysis_generates_annotation_and_json(self):
        from PIL import Image, ImageDraw

        image_path = self.upload_dir / "test-shirt.png"
        image = Image.new("RGB", (480, 640), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((150, 90, 330, 500), fill=(32, 94, 182))
        draw.rectangle((90, 130, 150, 280), fill=(32, 94, 182))
        draw.rectangle((330, 130, 390, 280), fill=(32, 94, 182))
        draw.rectangle((200, 60, 280, 115), fill="white")
        image.save(image_path)

        with self.app.app_context():
            factory = Factory(name="Test Factory")
            db.session.add(factory)
            db.session.flush()

            product = Product(
                factory_id=factory.id,
                name="Sample Tee",
                category="t_shirt",
                quantity=3,
                website_image="/uploads/test-shirt.png",
            )
            db.session.add(product)
            db.session.commit()

            service = GarmentImageAnalysisService()
            result = service.analyze_and_store(product)

            self.assertEqual(result["status"], "analyzed")
            self.assertTrue(product.garment_analysis_json)
            self.assertTrue(product.garment_annotation_image.startswith("/uploads/annotations/"))
            annotation_path = self.upload_dir / "annotations" / Path(product.garment_annotation_image).name
            self.assertTrue(annotation_path.exists())

    def test_garment_zone_assignment_can_link_to_composition_item(self):
        with self.app.app_context():
            factory = Factory(name="Assignment Factory")
            db.session.add(factory)
            db.session.flush()

            fabric = Fabric(
                factory_id=factory.id,
                name="Neck Label",
                material_type="label",
                unit="pcs",
                quantity=200,
                category="branding",
            )
            db.session.add(fabric)
            db.session.flush()

            product = Product(
                factory_id=factory.id,
                name="Mapped Tee",
                category="t_shirt",
                quantity=1,
            )
            db.session.add(product)
            db.session.flush()

            composition = ProductComposition(
                product_id=product.id,
                fabric_id=fabric.id,
                quantity_required=1,
                unit="pcs",
                note="inside neck",
            )
            db.session.add(composition)
            db.session.commit()

            service = GarmentImageAnalysisService()
            assignment = service.save_zone_assignment(
                product=product,
                zone_key="neck_label_area",
                zone_label="Neck label area",
                selection=f"comp:{composition.id}",
                usage_label="Brand label",
                note="auto test",
            )

            self.assertEqual(assignment.assignment_kind, "composition_item")
            self.assertEqual(assignment.product_composition_id, composition.id)
            self.assertEqual(assignment.fabric_id, fabric.id)
            self.assertEqual(assignment.usage_label, "Brand label")


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
            PUBLIC_TELEGRAM_URL = "https://t.me/adras_demo_bot"

        with self.assertRaisesRegex(RuntimeError, "SECRET_KEY"):
            create_app(UnsafeProdConfig)


class DeployPreflightCommandTestCase(unittest.TestCase):
    def setUp(self):
        base_tmp_dir = Path(__file__).resolve().parents[1] / ".tmp_test"
        base_tmp_dir.mkdir(exist_ok=True)
        self.temp_dir = Path(tempfile.mkdtemp(dir=base_tmp_dir)).resolve()
        self.db_path = (self.temp_dir / "test.db").resolve()
        self.old_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")

    def tearDown(self):
        if self.old_bot_token is None:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        else:
            os.environ["TELEGRAM_BOT_TOKEN"] = self.old_bot_token
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_prod_like_app(self, *, bootstrap: bool):
        import tempfile
        from pathlib import Path

        db_uri = f"sqlite:///{self.db_path}"
        upload_dir = Path(tempfile.mkdtemp(prefix="adras_uploads_"))

        class ProdLikeConfig:
            DEBUG = False
            TESTING = False
            SECRET_KEY = "test-prod-secret"
            SQLALCHEMY_DATABASE_URI = db_uri
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
            UPLOAD_FOLDER = str(upload_dir)
            ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
            MAX_CONTENT_LENGTH = 5 * 1024 * 1024
            SESSION_COOKIE_HTTPONLY = True
            SESSION_COOKIE_SAMESITE = "Lax"
            SESSION_COOKIE_SECURE = True
            REMEMBER_COOKIE_SECURE = True
            REMEMBER_COOKIE_HTTPONLY = True
            AUTO_DB_BOOTSTRAP = bootstrap
            PROD_ALLOW_SQLITE = True
            PUBLIC_TELEGRAM_URL = "https://t.me/adras_demo_bot"

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
