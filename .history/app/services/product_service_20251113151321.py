from datetime import date, datetime
from sqlalchemy import or_

from ..extensions import db
from ..models import Product, Sale, CashRecord


class ProductService:
    def list_products(self, query: str | None = None, category: str | None = None):
        q = Product.query

        if query:
            q_lower = f"%{query.lower()}%"
            q = q.filter(
                or_(
                    db.func.lower(Product.name).like(q_lower),
                    db.func.lower(Product.category).like(q_lower),
                )
            )

        if category:
            q = q.filter(db.func.lower(Product.category) == category.lower())

        return q.order_by(Product.name.asc()).all()

    def get_categories(self):
        rows = (
            db.session.query(Product.category)
            .filter(Product.category.isnot(None), Product.category != "")
            .distinct()
            .order_by(Product.category.asc())
            .all()
        )
        return [r[0] for r in rows]

    def add_product(self, name: str, category: str | None, quantity: int,
                    price_per_item: float | None, currency: str):
        product = Product(
            name=name,
            category=category,
            quantity=quantity,
            price_per_item=price_per_item,
            currency=currency,
        )
        db.session.add(product)
        db.session.commit()
        return product

    def increase_stock(self, product_id: int, quantity: int):
        product = Product.query.get(product_id)
        if not product or quantity <= 0:
            return False
        product.quantity += quantity
        db.session.commit()
        return True

    def sell_product(self, product_id: int, quantity: int, price_per_item: float | None = None):
        product = Product.query.get(product_id)
        if not product or quantity <= 0 or quantity > product.quantity:
            return None

        # If price not given, use current product price
        final_price = price_per_item if price_per_item is not None else (product.price_per_item or 0.0)

        product.quantity -= quantity
        sale = Sale(
            product_id=product.id,
            date=date.today(),
            quantity=quantity,
            price_per_item=final_price,
            currency=product.currency,
        )

        # Optional: also create cash record immediately
        cash = CashRecord(
            date=date.today(),
            amount=quantity * final_price,
            currency=product.currency,
            note=f"Sale of {product.name}",
        )

        db.session.add(sale)
        db.session.add(cash)
        db.session.commit()
        return sale

    def recent_sales(self, limit: int = 20):
        return (
            Sale.query.join(Product)
            .order_by(Sale.date.desc(), Sale.id.desc())
            .limit(limit)
            .all()
        )

    def total_stock_value(self):
        products = Product.query.all()
        total_uzs = 0.0
        total_usd = 0.0
        for p in products:
            if p.price_per_item is None:
                continue
            value = p.quantity * p.price_per_item
            if p.currency == "UZS":
                total_uzs += value
            elif p.currency == "USD":
                total_usd += value
        return total_uzs, total_usd
