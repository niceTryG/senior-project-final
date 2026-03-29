from flask import Blueprint, render_template, abort, current_app, request
from urllib.parse import quote

from sqlalchemy import or_, text, inspect

from ..models import Product
from ..extensions import db

public_bp = Blueprint("public", __name__)


def _telegram_url() -> str:
    return (current_app.config.get("PUBLIC_TELEGRAM_URL") or "").strip()


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
        "🧾 Mini Moda order\n"
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


# ======================
#   🏠 HOME
# ======================
@public_bp.route("/")
def home():
    col_exists = _product_column_exists("is_published")

    if not col_exists:
        return render_template(
            "public/home.html",
            products=[],
            public_telegram_url=_telegram_url(),
            tg_order_link=_tg_order_link,
        )

    products = (
        Product.query
        .filter(Product.is_published.is_(True))
        .order_by(Product.id.desc())
        .limit(6)
        .all()
    )

    return render_template(
        "public/home.html",
        products=products,
        public_telegram_url=_telegram_url(),
        tg_order_link=_tg_order_link,
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