from flask import Blueprint, render_template, abort, current_app, request
from urllib.parse import quote
from app import db 
from sqlalchemy import or_
from ..models import Product
from sqlalchemy.exc import SQLAlchemyError, ProgrammingError
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

    text = (
        "🧾 Mini Moda order\n"
        f"📌 Code: {code}\n"
        f"👕 Name: {name}\n"
        f"🔢 Qty: {qty_int}\n\n"
        "📞 Phone:\n"
        "📍 Address:"
    )

    return f"{base}?text={quote(text)}"

# ======================
#   🏠 HOME
# ======================
from sqlalchemy.exc import ProgrammingError
from app import db  # make sure this import exists

@public_bp.route("/")
def home():
    try:
        products = (
            Product.query
            .filter_by(is_published=True)
            .order_by(Product.id.desc())
            .limit(6)
            .all()
        )
    except (ProgrammingError, SQLAlchemyError):
        # DB schema mismatch (column missing), rollback and fallback
        db.session.rollback()
        products = (
            Product.query
            .order_by(Product.id.desc())
            .limit(6)
            .all()
        )

    return render_template("public/home.html", products=products)

# ======================
#   📦 CATALOG
# ======================
@public_bp.route("/catalog")
def catalog():
    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()

    base_q = Product.query.filter_by(is_published=True)

    # categories (published only)
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
    product = Product.query.filter_by(id=product_id, is_published=True).first()
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
    )