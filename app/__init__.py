import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import click
from flask import Flask, redirect, request, session, url_for
from flask.cli import with_appcontext
from flask_babel import get_locale, refresh
from flask_login import current_user
from jinja2 import Undefined

from app.extensions import MIGRATE_AVAILABLE, babel
from app.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, select_locale
from .db_migrations import migration_status, pending_migrations, upgrade_database
from .extensions import db, login_manager, migrate
from .models import User
from .translations import t as translate
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
        warnings.append(
            "SESSION_COOKIE_SAMESITE=None is less strict; use Lax unless cross-site flows require it."
        )

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


def _seed_demo_data() -> dict[str, list[str]]:
    from .models import (
        CashRecord,
        CuttingOrder,
        CuttingOrderMaterial,
        Fabric,
        FabricConsumption,
        Factory,
        Movement,
        OperationalTask,
        Product,
        ProductComposition,
        Production,
        Sale,
        Shop,
        ShopFactoryLink,
        ShopOrder,
        ShopOrderItem,
        ShopStock,
        StockMovement,
        User,
    )

    today = date.today()
    summary: dict[str, list[str]] = {"created": [], "updated": [], "skipped": []}

    def _remember(bucket: str, label: str) -> None:
        summary[bucket].append(label)

    def _sync_fields(obj, attrs: dict) -> bool:
        changed = False
        for key, value in attrs.items():
            if getattr(obj, key) != value:
                setattr(obj, key, value)
                changed = True
        return changed

    def _upsert(model, lookup: dict, attrs: dict, label: str):
        obj = model.query.filter_by(**lookup).first()
        if obj is None:
            obj = model(**lookup, **attrs)
            db.session.add(obj)
            _remember("created", label)
            return obj

        if _sync_fields(obj, attrs):
            _remember("updated", label)
        else:
            _remember("skipped", label)
        return obj

    def _upsert_user(*, username: str, password: str, label: str, attrs: dict) -> User:
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(username=username, **attrs)
            user.set_password(password)
            db.session.add(user)
            _remember("created", label)
            return user

        changed = _sync_fields(user, attrs)
        if not user.check_password(password):
            user.set_password(password)
            changed = True

        if changed:
            _remember("updated", label)
        else:
            _remember("skipped", label)
        return user

    factory = _upsert(
        Factory,
        {"name": "Adras Demo Factory"},
        {
            "location": "Tashkent",
            "owner_name": "Demo Owner",
            "phone": "+998900000000",
            "note": "Senior project demo factory",
        },
        "factory: Adras Demo Factory",
    )
    db.session.flush()

    shop = _upsert(
        Shop,
        {"name": "Adras Demo Shop"},
        {
            "factory_id": factory.id,
            "location": "Tashkent",
            "note": "Senior project demo shop",
            "is_active": True,
        },
        "shop: Adras Demo Shop",
    )
    db.session.flush()

    _upsert(
        ShopFactoryLink,
        {"shop_id": shop.id, "factory_id": factory.id},
        {},
        "shop-factory link: Adras Demo Shop <-> Adras Demo Factory",
    )

    _upsert_user(
        username="demo_superadmin",
        password="Demo123!",
        label="user: demo_superadmin",
        attrs={
            "full_name": "Demo Superadmin",
            "phone": "+998900000001",
            "role": "superadmin",
            "factory_id": None,
            "shop_id": None,
            "must_change_password": False,
            "failed_login_attempts": 0,
            "locked_until": None,
        },
    )

    manager = _upsert_user(
        username="demo_manager",
        password="Demo123!",
        label="user: demo_manager",
        attrs={
            "full_name": "Demo Manager",
            "phone": "+998900000002",
            "role": "manager",
            "factory_id": factory.id,
            "shop_id": None,
            "must_change_password": False,
            "failed_login_attempts": 0,
            "locked_until": None,
        },
    )
    db.session.flush()

    if factory.owner_user_id != manager.id:
        factory.owner_user_id = manager.id
        _remember("updated", "factory owner user: Adras Demo Factory")

    material_specs = [
        {
            "name": "Cotton Jersey Blue",
            "color": "Blue",
            "material_type": "fabric",
            "unit": "kg",
            "quantity": 120.0,
            "min_stock_quantity": 10.0,
            "price_currency": "UZS",
            "price_per_unit": 78000.0,
            "category": "Knit Fabric",
            "supplier_name": "Adras Textile Supply",
        },
        {
            "name": "Cotton Jersey White",
            "color": "White",
            "material_type": "fabric",
            "unit": "kg",
            "quantity": 95.0,
            "min_stock_quantity": 10.0,
            "price_currency": "UZS",
            "price_per_unit": 76000.0,
            "category": "Knit Fabric",
            "supplier_name": "Adras Textile Supply",
        },
        {
            "name": "Rib Knit Black",
            "color": "Black",
            "material_type": "fabric",
            "unit": "kg",
            "quantity": 48.0,
            "min_stock_quantity": 5.0,
            "price_currency": "UZS",
            "price_per_unit": 69000.0,
            "category": "Trim Fabric",
            "supplier_name": "Adras Textile Supply",
        },
        {
            "name": "Fleece Gray",
            "color": "Gray",
            "material_type": "fabric",
            "unit": "kg",
            "quantity": 82.0,
            "min_stock_quantity": 8.0,
            "price_currency": "UZS",
            "price_per_unit": 93000.0,
            "category": "Warm Fabric",
            "supplier_name": "Adras Textile Supply",
        },
        {
            "name": "Interlock Cream",
            "color": "Cream",
            "material_type": "fabric",
            "unit": "kg",
            "quantity": 60.0,
            "min_stock_quantity": 6.0,
            "price_currency": "UZS",
            "price_per_unit": 81000.0,
            "category": "Soft Fabric",
            "supplier_name": "Adras Textile Supply",
        },
        {
            "name": "Woven Label White",
            "color": "White",
            "material_type": "label",
            "unit": "pcs",
            "quantity": 5000.0,
            "min_stock_quantity": 500.0,
            "price_currency": "UZS",
            "price_per_unit": 250.0,
            "category": "Label",
            "supplier_name": "Adras Trims",
        },
        {
            "name": "Drawcord Black",
            "color": "Black",
            "material_type": "accessory",
            "unit": "pcs",
            "quantity": 1200.0,
            "min_stock_quantity": 100.0,
            "price_currency": "UZS",
            "price_per_unit": 900.0,
            "category": "Accessory",
            "supplier_name": "Adras Trims",
        },
    ]

    fabric_lookup: dict[str, Fabric] = {}
    for spec in material_specs:
        fabric = _upsert(
            Fabric,
            {"factory_id": factory.id, "name": spec["name"]},
            {
                "color": spec["color"],
                "material_type": spec["material_type"],
                "unit": spec["unit"],
                "quantity": spec["quantity"],
                "min_stock_quantity": spec["min_stock_quantity"],
                "price_currency": spec["price_currency"],
                "price_per_unit": spec["price_per_unit"],
                "category": spec["category"],
                "supplier_name": spec["supplier_name"],
            },
            f"material: {spec['name']}",
        )
        fabric_lookup[spec["name"]] = fabric
    db.session.flush()

    product_specs = [
        {
            "name": "Basic T-Shirt Blue",
            "category": "T-Shirt",
            "cost": 52000.0,
            "sell": 89000.0,
            "transfer": 68000.0,
            "quantity": 32,
            "description": "Classic blue t-shirt for the core demo flow.",
            "fabric_used": "Cotton Jersey Blue",
            "compositions": [
                ("Cotton Jersey Blue", 0.32, "kg"),
                ("Woven Label White", 1.0, "pcs"),
            ],
        },
        {
            "name": "Basic T-Shirt White",
            "category": "T-Shirt",
            "cost": 50000.0,
            "sell": 86000.0,
            "transfer": 66000.0,
            "quantity": 28,
            "description": "Clean white t-shirt for product and sales screens.",
            "fabric_used": "Cotton Jersey White",
            "compositions": [
                ("Cotton Jersey White", 0.31, "kg"),
                ("Woven Label White", 1.0, "pcs"),
            ],
        },
        {
            "name": "Kids Hoodie Gray",
            "category": "Hoodie",
            "cost": 88000.0,
            "sell": 145000.0,
            "transfer": 112000.0,
            "quantity": 20,
            "description": "Soft gray hoodie for the production demo.",
            "fabric_used": "Fleece Gray",
            "compositions": [
                ("Fleece Gray", 0.58, "kg"),
                ("Drawcord Black", 1.0, "pcs"),
                ("Woven Label White", 1.0, "pcs"),
            ],
        },
        {
            "name": "Baby Set Cream",
            "category": "Set",
            "cost": 74000.0,
            "sell": 118000.0,
            "transfer": 93000.0,
            "quantity": 18,
            "description": "Cream baby set used for the dashboard and shop pages.",
            "fabric_used": "Interlock Cream",
            "compositions": [
                ("Interlock Cream", 0.47, "kg"),
                ("Woven Label White", 1.0, "pcs"),
            ],
        },
        {
            "name": "Jogger Pants Black",
            "category": "Pants",
            "cost": 69000.0,
            "sell": 112000.0,
            "transfer": 86000.0,
            "quantity": 24,
            "description": "Black jogger pants with a simple trim material mix.",
            "fabric_used": "Rib Knit Black",
            "compositions": [
                ("Rib Knit Black", 0.42, "kg"),
                ("Drawcord Black", 1.0, "pcs"),
                ("Woven Label White", 1.0, "pcs"),
            ],
        },
        {
            "name": "Polo Shirt White",
            "category": "Shirt",
            "cost": 64000.0,
            "sell": 105000.0,
            "transfer": 81000.0,
            "quantity": 22,
            "description": "White polo shirt for a slightly smarter product example.",
            "fabric_used": "Cotton Jersey White",
            "compositions": [
                ("Cotton Jersey White", 0.36, "kg"),
                ("Woven Label White", 1.0, "pcs"),
            ],
        },
        {
            "name": "Sweatshirt Gray",
            "category": "Sweatshirt",
            "cost": 79000.0,
            "sell": 128000.0,
            "transfer": 98000.0,
            "quantity": 21,
            "description": "Gray sweatshirt for inventory and costing pages.",
            "fabric_used": "Fleece Gray",
            "compositions": [
                ("Fleece Gray", 0.51, "kg"),
                ("Woven Label White", 1.0, "pcs"),
            ],
        },
        {
            "name": "Zipper Hoodie Black",
            "category": "Hoodie",
            "cost": 93000.0,
            "sell": 152000.0,
            "transfer": 118000.0,
            "quantity": 16,
            "description": "Black hoodie used to show higher-value items.",
            "fabric_used": "Rib Knit Black",
            "compositions": [
                ("Rib Knit Black", 0.55, "kg"),
                ("Drawcord Black", 1.0, "pcs"),
                ("Woven Label White", 1.0, "pcs"),
            ],
        },
        {
            "name": "Long Sleeve Top Blue",
            "category": "Top",
            "cost": 61000.0,
            "sell": 98000.0,
            "transfer": 76000.0,
            "quantity": 19,
            "description": "Blue long sleeve top with simple demo numbers.",
            "fabric_used": "Cotton Jersey Blue",
            "compositions": [
                ("Cotton Jersey Blue", 0.39, "kg"),
                ("Woven Label White", 1.0, "pcs"),
            ],
        },
        {
            "name": "Kids Leggings Black",
            "category": "Leggings",
            "cost": 57000.0,
            "sell": 92000.0,
            "transfer": 71000.0,
            "quantity": 26,
            "description": "Simple black leggings for stock and order screens.",
            "fabric_used": "Rib Knit Black",
            "compositions": [
                ("Rib Knit Black", 0.33, "kg"),
                ("Woven Label White", 1.0, "pcs"),
            ],
        },
        {
            "name": "Baby Bodysuit Cream",
            "category": "Babywear",
            "cost": 56000.0,
            "sell": 91000.0,
            "transfer": 70000.0,
            "quantity": 27,
            "description": "Cream bodysuit for the babywear part of the demo.",
            "fabric_used": "Interlock Cream",
            "compositions": [
                ("Interlock Cream", 0.29, "kg"),
                ("Woven Label White", 1.0, "pcs"),
            ],
        },
        {
            "name": "Sports Set Blue",
            "category": "Set",
            "cost": 84000.0,
            "sell": 136000.0,
            "transfer": 104000.0,
            "quantity": 17,
            "description": "Blue sports set used across stock, sales, and reporting pages.",
            "fabric_used": "Cotton Jersey Blue",
            "compositions": [
                ("Cotton Jersey Blue", 0.54, "kg"),
                ("Woven Label White", 1.0, "pcs"),
            ],
        },
    ]

    product_lookup: dict[str, Product] = {}
    for spec in product_specs:
        product = _upsert(
            Product,
            {"factory_id": factory.id, "name": spec["name"]},
            {
                "category": spec["category"],
                "cost_price_per_item": spec["cost"],
                "sell_price_per_item": spec["sell"],
                "factory_transfer_price": spec["transfer"],
                "website_image": None,
                "fabric_used": spec["fabric_used"],
                "notes": "Senior project demo product",
                "quantity": spec["quantity"],
                "currency": "UZS",
                "image_path": None,
                "is_published": True,
                "public_description": spec["description"],
                "garment_analysis_json": None,
                "garment_annotation_image": None,
                "garment_analysis_version": None,
                "garment_analysis_updated_at": None,
            },
            f"product: {spec['name']}",
        )
        product_lookup[spec["name"]] = product
    db.session.flush()

    for spec in product_specs:
        product = product_lookup[spec["name"]]
        for fabric_name, quantity_required, unit in spec["compositions"]:
            fabric = fabric_lookup[fabric_name]
            _upsert(
                ProductComposition,
                {"product_id": product.id, "fabric_id": fabric.id},
                {
                    "quantity_required": quantity_required,
                    "unit": unit,
                    "note": "Senior project demo composition",
                },
                f"composition: {spec['name']} -> {fabric_name}",
            )

    shop_stock_specs = [
        ("Basic T-Shirt Blue", 9),
        ("Basic T-Shirt White", 8),
        ("Kids Hoodie Gray", 6),
        ("Baby Set Cream", 5),
        ("Jogger Pants Black", 7),
        ("Polo Shirt White", 6),
        ("Sweatshirt Gray", 5),
        ("Zipper Hoodie Black", 4),
        ("Long Sleeve Top Blue", 5),
        ("Kids Leggings Black", 7),
        ("Baby Bodysuit Cream", 8),
        ("Sports Set Blue", 4),
    ]
    for product_name, quantity in shop_stock_specs:
        product = product_lookup[product_name]
        _upsert(
            ShopStock,
            {
                "shop_id": shop.id,
                "product_id": product.id,
                "source_factory_id": factory.id,
            },
            {"quantity": quantity},
            f"shop stock: {product_name}",
        )

    production_specs = [
        {
            "product_name": "Basic T-Shirt Blue",
            "days_ago": 7,
            "quantity": 18,
            "finished_good": 17,
            "defective": 1,
            "note": "Senior project demo production run A",
            "fabric_name": "Cotton Jersey Blue",
            "used_amount": 5.8,
        },
        {
            "product_name": "Kids Hoodie Gray",
            "days_ago": 5,
            "quantity": 12,
            "finished_good": 11,
            "defective": 1,
            "note": "Senior project demo production run B",
            "fabric_name": "Fleece Gray",
            "used_amount": 7.1,
        },
        {
            "product_name": "Baby Set Cream",
            "days_ago": 3,
            "quantity": 10,
            "finished_good": 10,
            "defective": 0,
            "note": "Senior project demo production run C",
            "fabric_name": "Interlock Cream",
            "used_amount": 4.7,
        },
        {
            "product_name": "Jogger Pants Black",
            "days_ago": 1,
            "quantity": 14,
            "finished_good": 13,
            "defective": 1,
            "note": "Senior project demo production run D",
            "fabric_name": "Rib Knit Black",
            "used_amount": 5.9,
        },
    ]

    production_lookup: dict[str, Production] = {}
    for spec in production_specs:
        product = product_lookup[spec["product_name"]]
        production = _upsert(
            Production,
            {
                "product_id": product.id,
                "date": today - timedelta(days=spec["days_ago"]),
                "note": spec["note"],
            },
            {
                "quantity": spec["quantity"],
                "qty_issued_to_workers": spec["quantity"],
                "qty_finished_good": spec["finished_good"],
                "qty_defective": spec["defective"],
                "qty_unfinished": 0,
                "qty_payable": spec["finished_good"],
                "shortfall_reason": None if spec["defective"] == 0 else "Minor sewing correction",
                "production_plan_id": None,
            },
            f"production: {spec['product_name']} ({spec['note']})",
        )
        production_lookup[spec["note"]] = production
    db.session.flush()

    for spec in production_specs:
        production = production_lookup[spec["note"]]
        fabric = fabric_lookup[spec["fabric_name"]]
        _upsert(
            FabricConsumption,
            {
                "factory_id": factory.id,
                "fabric_id": fabric.id,
                "production_id": production.id,
            },
            {"used_amount": spec["used_amount"]},
            f"fabric consumption: {spec['product_name']} -> {spec['fabric_name']}",
        )

    cutting_order_specs = [
        {
            "product_name": "Kids Hoodie Gray",
            "days_ago": 4,
            "sets_cut": 12,
            "status": "open",
            "notes": "Senior project demo cutting order 1",
            "materials": [
                ("Fleece Gray", 6.0),
                ("Drawcord Black", 12.0),
            ],
        },
        {
            "product_name": "Jogger Pants Black",
            "days_ago": 2,
            "sets_cut": 14,
            "status": "open",
            "notes": "Senior project demo cutting order 2",
            "materials": [
                ("Rib Knit Black", 5.2),
                ("Drawcord Black", 14.0),
            ],
        },
    ]

    for spec in cutting_order_specs:
        product = product_lookup[spec["product_name"]]
        cutting_order = _upsert(
            CuttingOrder,
            {
                "factory_id": factory.id,
                "product_id": product.id,
                "cut_date": today - timedelta(days=spec["days_ago"]),
            },
            {
                "sets_cut": spec["sets_cut"],
                "status": spec["status"],
                "notes": spec["notes"],
                "created_by_id": manager.id,
            },
            f"cutting order: {spec['product_name']}",
        )
        db.session.flush()

        for material_name, used_amount in spec["materials"]:
            material = fabric_lookup[material_name]
            unit_cost = float(material.price_per_unit or 0.0)
            _upsert(
                CuttingOrderMaterial,
                {
                    "cutting_order_id": cutting_order.id,
                    "material_id": material.id,
                },
                {
                    "used_amount": used_amount,
                    "unit_cost_snapshot": unit_cost,
                    "total_cost_snapshot": round(unit_cost * used_amount, 2),
                },
                f"cutting material: {spec['product_name']} -> {material_name}",
            )

    sale_specs = [
        ("Basic T-Shirt Blue", 6, "Akmal Karimov", "+998901111111", 2),
        ("Kids Hoodie Gray", 5, "Nodira Ismailova", "+998902222222", 1),
        ("Baby Set Cream", 4, "Aziza Yuldasheva", "+998903333333", 2),
        ("Jogger Pants Black", 3, "Sardor Mamatov", "+998904444444", 1),
        ("Long Sleeve Top Blue", 2, "Dilnoza Rakhimova", "+998905555555", 2),
        ("Baby Bodysuit Cream", 1, "Kamila Saidova", "+998906666666", 1),
    ]
    for product_name, days_ago, customer_name, customer_phone, quantity in sale_specs:
        product = product_lookup[product_name]
        _upsert(
            Sale,
            {
                "product_id": product.id,
                "shop_id": shop.id,
                "date": today - timedelta(days=days_ago),
                "customer_name": customer_name,
            },
            {
                "created_by_id": manager.id,
                "customer_phone": customer_phone,
                "quantity": quantity,
                "sell_price_per_item": product.sell_price_per_item,
                "cost_price_per_item": product.cost_price_per_item,
                "currency": "UZS",
            },
            f"sale: {product_name} -> {customer_name}",
        )

    cash_specs = [
        (6, 550000.0, "Demo sales cash received"),
        (4, 320000.0, "Demo material payment reserve"),
        (2, 470000.0, "Demo weekly cash balance"),
        (0, 610000.0, "Demo current cash on hand"),
    ]
    for days_ago, amount, note in cash_specs:
        _upsert(
            CashRecord,
            {
                "factory_id": factory.id,
                "date": today - timedelta(days=days_ago),
                "note": note,
            },
            {
                "amount": amount,
                "currency": "UZS",
            },
            f"cash record: {note}",
        )

    order_specs = [
        {
            "customer_name": "School Uniform Desk",
            "customer_phone": "+998907777777",
            "note": "Senior project demo order A",
            "status": "pending",
            "days_ago": 3,
            "ready_days_ago": None,
            "completed_days_ago": None,
            "items": [
                ("Basic T-Shirt White", 6, 2, 4),
                ("Jogger Pants Black", 4, 1, 3),
            ],
        },
        {
            "customer_name": "Family Clothing Order",
            "customer_phone": "+998908888888",
            "note": "Senior project demo order B",
            "status": "ready",
            "days_ago": 2,
            "ready_days_ago": 1,
            "completed_days_ago": None,
            "items": [
                ("Baby Set Cream", 3, 3, 0),
                ("Baby Bodysuit Cream", 4, 4, 0),
            ],
        },
        {
            "customer_name": "Sport Club Request",
            "customer_phone": "+998909999999",
            "note": "Senior project demo order C",
            "status": "pending",
            "days_ago": 1,
            "ready_days_ago": None,
            "completed_days_ago": None,
            "items": [
                ("Sports Set Blue", 5, 2, 3),
            ],
        },
    ]

    for spec in order_specs:
        created_at = datetime.combine(
            today - timedelta(days=spec["days_ago"]),
            datetime.min.time(),
        ) + timedelta(hours=11)
        ready_at = None
        if spec["ready_days_ago"] is not None:
            ready_at = datetime.combine(
                today - timedelta(days=spec["ready_days_ago"]),
                datetime.min.time(),
            ) + timedelta(hours=16)
        completed_at = None
        if spec["completed_days_ago"] is not None:
            completed_at = datetime.combine(
                today - timedelta(days=spec["completed_days_ago"]),
                datetime.min.time(),
            ) + timedelta(hours=18)

        order = _upsert(
            ShopOrder,
            {
                "factory_id": factory.id,
                "customer_name": spec["customer_name"],
                "note": spec["note"],
            },
            {
                "customer_phone": spec["customer_phone"],
                "status": spec["status"],
                "ready_at": ready_at,
                "completed_at": completed_at,
                "created_by_id": manager.id,
                "created_at": created_at,
            },
            f"shop order: {spec['customer_name']}",
        )
        db.session.flush()

        for product_name, qty_requested, qty_from_shop_now, qty_remaining in spec["items"]:
            product = product_lookup[product_name]
            _upsert(
                ShopOrderItem,
                {"order_id": order.id, "product_id": product.id},
                {
                    "qty_requested": qty_requested,
                    "qty_from_shop_now": qty_from_shop_now,
                    "qty_remaining": qty_remaining,
                },
                f"shop order item: {spec['customer_name']} -> {product_name}",
            )

    movement_specs = [
        ("Basic T-Shirt Blue", "Factory", "Demo Shop", 9, "Senior project demo transfer: t-shirt"),
        ("Kids Hoodie Gray", "Factory", "Demo Shop", 6, "Senior project demo transfer: hoodie"),
        ("Baby Set Cream", "Factory", "Demo Shop", 5, "Senior project demo transfer: baby set"),
    ]
    for product_name, source, destination, change, note in movement_specs:
        product = product_lookup[product_name]
        _upsert(
            Movement,
            {
                "factory_id": factory.id,
                "product_id": product.id,
                "note": note,
            },
            {
                "source": source,
                "destination": destination,
                "change": change,
                "created_by_id": manager.id,
            },
            f"movement: {product_name}",
        )

    stock_movement_specs = [
        ("Basic T-Shirt Blue", 9, "factory_stock", "shop_stock", "transfer", "Senior project demo stock movement: t-shirt"),
        ("Kids Hoodie Gray", 6, "factory_stock", "shop_stock", "transfer", "Senior project demo stock movement: hoodie"),
        ("Baby Set Cream", 5, "factory_stock", "shop_stock", "transfer", "Senior project demo stock movement: baby set"),
    ]
    for product_name, qty_change, source, destination, movement_type, comment in stock_movement_specs:
        product = product_lookup[product_name]
        _upsert(
            StockMovement,
            {
                "factory_id": factory.id,
                "product_id": product.id,
                "comment": comment,
            },
            {
                "qty_change": qty_change,
                "unit_price": product.factory_transfer_price,
                "total_value": round((product.factory_transfer_price or 0.0) * qty_change, 2),
                "currency": "UZS",
                "locked_unit_price": product.factory_transfer_price,
                "locked_total_value": round((product.factory_transfer_price or 0.0) * qty_change, 2),
                "source": source,
                "destination": destination,
                "movement_type": movement_type,
                "order_id": None,
            },
            f"stock movement: {product_name}",
        )

    task_specs = [
        {
            "title": "Review low stock materials",
            "description": "Check black rib knit and plan the next fabric purchase.",
            "action_url": "/materials",
            "priority": "high",
            "due_days": 1,
        },
        {
            "title": "Prepare next weekly production batch",
            "description": "Review shop demand and confirm the next production run.",
            "action_url": "/dashboard/command-center",
            "priority": "medium",
            "due_days": 2,
        },
    ]
    for spec in task_specs:
        _upsert(
            OperationalTask,
            {
                "factory_id": factory.id,
                "title": spec["title"],
            },
            {
                "shop_id": shop.id,
                "assigned_user_id": manager.id,
                "created_by_id": manager.id,
                "closed_by_id": None,
                "task_type": "manual",
                "source_type": "demo_seed",
                "source_id": None,
                "description": spec["description"],
                "action_url": spec["action_url"],
                "target_role": "manager",
                "priority": spec["priority"],
                "status": "open",
                "due_date": today + timedelta(days=spec["due_days"]),
                "is_system_generated": False,
                "closed_at": None,
            },
            f"task: {spec['title']}",
        )

    db.session.commit()
    return summary


def create_app(config_class="config.DevConfig"):
    app = Flask(__name__)
    app.config.from_object(config_class)
    _validate_runtime_config(app)

    app.config["BABEL_DEFAULT_LOCALE"] = DEFAULT_LANGUAGE
    app.config["BABEL_TRANSLATION_DIRECTORIES"] = "translations"

    babel.init_app(app, locale_selector=select_locale)

    db.init_app(app)
    if migrate is not None:
        migrate.init_app(app, db, compare_type=True, render_as_batch=True)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    if app.config.get("AUTO_DB_BOOTSTRAP", False):
        with app.app_context():
            _bootstrap_database()

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except (TypeError, ValueError):
            return None

    @app.before_request
    def require_login():
        if request.endpoint and request.endpoint.startswith("static"):
            return

        if request.endpoint in ("auth.login", "auth.logout", "auth.security_wall"):
            return

        if request.endpoint == "switch_language":
            return

        if request.endpoint and request.endpoint.startswith("public."):
            return

        if request.path.startswith("/setup/") or request.path.startswith("/auth/setup/"):
            return

        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))

        if getattr(current_user, "must_change_password", False):
            if request.endpoint not in {"auth.security_wall", "auth.logout", "switch_language"}:
                return redirect(url_for("auth.security_wall"))

        if getattr(current_user, "is_superadmin", False):
            return

        if "factory_id" not in session:
            from .models import Factory

            first_factory = Factory.query.first()
            if first_factory:
                session["factory_id"] = first_factory.id
            elif app.config.get("AUTO_DB_BOOTSTRAP", False):
                if getattr(current_user, "role", None) == "admin":
                    default_factory = Factory(name="Adras Factory")
                    db.session.add(default_factory)
                    db.session.commit()
                    session["factory_id"] = default_factory.id

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

    @app.cli.command("seed-demo-data")
    @with_appcontext
    def seed_demo_data_command():
        summary = _seed_demo_data()

        click.echo("Demo dataset ready.")
        click.echo(f"Created: {len(summary['created'])}")
        for item in summary["created"]:
            click.echo(f"  + {item}")

        click.echo(f"Updated: {len(summary['updated'])}")
        for item in summary["updated"]:
            click.echo(f"  ~ {item}")

        click.echo(f"Unchanged: {len(summary['skipped'])}")
        for item in summary["skipped"]:
            click.echo(f"  = {item}")

        click.echo("Demo credentials:")
        click.echo("  demo_superadmin / Demo123!")
        click.echo("  demo_manager / Demo123!")

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
            "_": _t,
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

    @app.route("/lang/<lang_code>")
    def switch_language(lang_code):
        if lang_code not in SUPPORTED_LANGUAGES:
            lang_code = DEFAULT_LANGUAGE

        session["lang"] = lang_code
        session["lang_code"] = lang_code

        refresh()

        ref = request.referrer
        if ref:
            return redirect(ref)

        return redirect(url_for("main.dashboard"))

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
