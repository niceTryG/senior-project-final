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

    def add_product(self, name: str, category: str | None,
                    quantity: int,
                    cost_price_per_item: float | None,
                    sell_price_per_item: float | None,
                    currency: str):
        product = Product(
            name=name,
            category=category,
            quantity=quantity,
            cost_price_per_item=cost_price_per_item or 0.0,
            sell_price_per_item=sell_price_per_item or 0.0,
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

    def sell_product(
        self,
        product_id: int,
        quantity: int,
        customer_name: str | None = None,
        customer_phone: str | None = None,
        sell_price_override: float | None = None,
    ):
        product = Product.query.get(product_id)
        if not product or quantity <= 0 or quantity > product.quantity:
            return None

        # если цену не указали — берём из продукта
        sell_price = sell_price_override if sell_price_override is not None else product.sell_price_per_item
        cost_price = product.cost_price_per_item

        product.quantity -= quantity

        sale = Sale(
            product_id=product.id,
            date=date.today(),
            quantity=quantity,
            customer_name=customer_name or None,
            customer_phone=customer_phone or None,
            sell_price_per_item=sell_price,
            cost_price_per_item=cost_price,
            currency=product.currency,
        )

        # записываем в кассу выручку (по цене продажи)
        cash = CashRecord(
            date=date.today(),
            amount=sale.total_sell,
            currency=product.currency,
            note=f"Продажа {product.name} x{quantity} покупатель {customer_name or ''}",
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
            value = p.stock_value_cost()
            if p.currency == "USD":
                total_usd += value
            else:
                total_uzs += value
        return total_uzs, total_usd
   def sales_totals(self):
        """Return sales totals for today and current month, separated by currency."""
        today = date.today()
        month_start = date(today.year, today.month, 1)

        # All sales for today
        today_sales = (
            Sale.query.filter(Sale.date == today).all()
        )

        # All sales for current month
        month_sales = (
            Sale.query.filter(Sale.date >= month_start, Sale.date <= today).all()
        )

        def sum_by_currency(sales_list):
            totals = {}
            for s in sales_list:
                cur = s.currency or "UZS"
                totals.setdefault(cur, 0.0)
                totals[cur] += s.total_amount
            return totals

        return {
            "today": sum_by_currency(today_sales),
            "month": sum_by_currency(month_sales),
        }
    def list_sales(self, date_from=None, date_to=None):
        """Return all sales, optionally filtered by date range."""
        q = Sale.query.join(Product)

        if date_from:
            q = q.filter(Sale.date >= date_from)
        if date_to:
            q = q.filter(Sale.date <= date_to)

        return q.order_by(Sale.date.desc(), Sale.id.desc()).all()
