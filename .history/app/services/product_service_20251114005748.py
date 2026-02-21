from datetime import date, datetime
from sqlalchemy import or_
from datetime import date, timedelta
from ..extensions import db
from ..models import Product, Sale, CashRecord, Production, ShopStock, Fabric

from datetime import date
from sqlalchemy import func


LOW_STOCK_THRESHOLD = 20 # you can change this later or move to settings


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

    def add_product(
        self,
        name: str,
        category: str | None,
        quantity: int,
        cost_price_per_item: float | None,
        sell_price_per_item: float | None,
        currency: str,
    ):
        name_clean = name.strip()
        category_clean = (category or "").strip()
        qty = max(quantity, 0)

        # 1) Try to find existing matching product
        existing = (
            Product.query
            .filter(
                db.func.lower(Product.name) == name_clean.lower(),
                db.func.lower(db.func.coalesce(Product.category, "")) == category_clean.lower(),
                Product.currency == currency,
            )
            .first()
        )

        if existing:
            # --- MERGE LOGIC: update quantity and prices ---
            old_qty = existing.quantity
            new_qty = qty

            # update quantity
            existing.quantity = old_qty + new_qty

            # update cost price with weighted average if new cost provided
            if new_qty > 0 and cost_price_per_item is not None:
                old_cost = existing.cost_price_per_item or 0.0
                new_cost = cost_price_per_item

                total_cost_old = old_cost * old_qty
                total_cost_new = new_cost * new_qty
                total_qty = old_qty + new_qty

                if total_qty > 0:
                    existing.cost_price_per_item = (total_cost_old + total_cost_new) / total_qty

            # update sell price: if user provided a new sell price, overwrite
            if sell_price_per_item is not None and sell_price_per_item > 0:
                existing.sell_price_per_item = sell_price_per_item

            # log production for this batch
            if new_qty > 0:
                prod = Production(
                    product_id=existing.id,
                    quantity=new_qty,
                    note=None,
                )
                db.session.add(prod)

            db.session.commit()
            return existing

        # 2) No existing product → create a new one
        product = Product(
            name=name_clean,
            category=category_clean or None,
            quantity=qty,
            cost_price_per_item=cost_price_per_item or 0.0,
            sell_price_per_item=sell_price_per_item or 0.0,
            currency=currency,
        )
        db.session.add(product)
        db.session.flush()  # get product.id without full commit yet

        if qty > 0:
            prod = Production(
                product_id=product.id,
                quantity=qty,
                note=None,
            )
            db.session.add(prod)

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
        if not product or quantity <= 0:
            return None

        shop_stock = self._get_or_create_shop_stock(product_id)

        # cannot sell more than what is in the shop
        if quantity > shop_stock.quantity:
            return None

        # prices
        sell_price = sell_price_override if sell_price_override is not None else product.sell_price_per_item
        cost_price = product.cost_price_per_item

        # reduce only shop stock (factory stock already left earlier)
        shop_stock.quantity -= quantity

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
                totals[cur] += s.total_sell
                
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
    def production_stats(self):
        from sqlalchemy import func

        total_all = db.session.query(func.coalesce(func.sum(Production.quantity), 0)).scalar()

        total_today = (
            db.session.query(func.coalesce(func.sum(Production.quantity), 0))
            .filter(Production.date == date.today())
            .scalar()
        )

        return {
            "total_all": total_all or 0,
            "total_today": total_today or 0,
        }
    def stock_value_sell_totals(self):
        """Total stock value at SELL price, by currency."""
        products = Product.query.all()
        total_uzs = 0.0
        total_usd = 0.0

        for p in products:
            value = p.stock_value_sell()
            if p.currency == "USD":
                total_usd += value
            else:
                total_uzs += value

        return total_uzs, total_usd

    def stock_profit_totals(self):
        """Total potential profit in all remaining stock, by currency."""
        products = Product.query.all()
        total_uzs = 0.0
        total_usd = 0.0

        for p in products:
            profit = p.stock_profit()
            if p.currency == "USD":
                total_usd += profit
            else:
                total_uzs += profit

        return total_uzs, total_usd
    def get_low_stock_products(self):
        """Return products where quantity is at or below the low stock threshold."""
        return Product.query.filter(Product.quantity <= LOW_STOCK_THRESHOLD).order_by(Product.quantity.asc()).all()
    def _get_or_create_shop_stock(self, product_id: int) -> ShopStock:
        stock = ShopStock.query.filter_by(product_id=product_id).first()
        if not stock:
            stock = ShopStock(product_id=product_id, quantity=0)
            db.session.add(stock)
            db.session.flush()  # to get id
        return stock
    def transfer_to_shop(self, product_id: int, quantity: int):
        """Move ready products from factory stock to shop stock."""
        product = Product.query.get(product_id)
        if not product or quantity <= 0:
            return None

        if quantity > product.quantity:
            # not enough in factory
            return None

        product.quantity -= quantity
        shop_stock = self._get_or_create_shop_stock(product_id)
        shop_stock.quantity += quantity

        db.session.commit()
        return shop_stock
    def list_shop_stock(self):
        """All products currently in the shop."""
        return ShopStock.query.join(Product).order_by(Product.name.asc()).all()

    def shop_stock_totals(self):
        """Total money currently in shop (unsold goods), by currency."""
        stocks = ShopStock.query.join(Product).all()
        total_uzs = 0.0
        total_usd = 0.0

        for s in stocks:
            value = s.total_value
            cur = s.product.currency or "UZS"
            if cur == "USD":
                total_usd += value
            else:
                total_uzs += value

        return total_uzs, total_usd


    def weekly_shop_report(self):
        """Return weekly report for Monday–Saturday shop activity."""

        today = date.today()
        weekday = today.weekday()  # Monday=0
        monday = today - timedelta(days=weekday)
        sunday = monday + timedelta(days=6)

        # 1) Find all products currently in shop
        shop = ShopStock.query.join(Product).all()

        report = []

        for item in shop:
            product = item.product

            # Sales this week (Mon–Sun)
            sales = (
                Sale.query
                .filter(
                    Sale.product_id == product.id,
                    Sale.date >= monday,
                    Sale.date <= sunday
                )
                .all()
            )

            sold_qty = sum(s.quantity for s in sales)
            sent_qty = item.quantity + sold_qty  # sent = current + sold

            total_value = item.total_value

            report.append({
                "product": product,
                "sent": sent_qty,
                "sold": sold_qty,
                "remaining": item.quantity,
                "total_value": total_value,
            })

        # Totals
        total_sent = sum(r["sent"] * r["product"].sell_price_per_item for r in report)
        total_sold = sum(r["sold"] * r["product"].sell_price_per_item for r in report)
        total_remaining = sum(r["total_value"] for r in report)

        return {
            "monday": monday,
            "sunday": sunday,
            "rows": report,
            "total_sent": total_sent,
            "total_sold": total_sold,
            "total_remaining": total_remaining,
            "weekly_profit": total_sold,  # profit = sold revenue (cost tracking later)
        }

    def get_monthly_report(self):

     today = date.today()
     month_start = date(today.year, today.month, 1)

     # Sales this month
     sales = (
         Sale.query
         .filter(Sale.date >= month_start, Sale.date <= today)
         .all()
     )

     # Daily totals
     daily_totals = (
         db.session.query(
             Sale.date,
             func.sum(Sale.quantity * Sale.sell_price_per_item).label("total")
         )
         .filter(Sale.date >= month_start, Sale.date <= today)
         .group_by(Sale.date)
         .order_by(Sale.date.asc())
         .all()
     )
 
     # Best products
     top_products = (
         db.session.query(
             Product.name,
             func.sum(Sale.quantity).label("qty")
         )
         .join(Sale)
         .filter(Sale.date >= month_start, Sale.date <= today)
         .group_by(Product.id)
         .order_by(func.sum(Sale.quantity).desc())
         .limit(10)
         .all()
     )
 
     # Total revenue & profit
     total_revenue = sum(s.total_sell for s in sales)
     total_cost = sum(s.total_cost for s in sales)
     profit = total_revenue - total_cost
 
     return {
          "daily_totals": daily_totals,
         "top_products": top_products,
         "total_revenue": total_revenue,
         "total_cost": total_cost,
         "profit": profit,
     }
    def get_manager_financial_report(self):
        """Full financial overview for manager (Dad). All values in UZS only."""

        # ---- 1) Factory stock value (cost price, UZS only) ----
        products = Product.query.all()
        factory_cost_uzs = 0.0
        for p in products:
            cur = (p.currency or "UZS").upper()
            if cur != "UZS":
                continue
            qty_factory = p.quantity or 0
            cost_price = p.cost_price_per_item or 0.0
            factory_cost_uzs += qty_factory * cost_price

        # ---- 2) Shop stock value (sell price, UZS only) ----
        shop_sell_uzs = 0.0
        shop_items = ShopStock.query.join(Product).all()
        for s in shop_items:
            p = s.product
            cur = (p.currency or "UZS").upper()
            if cur != "UZS":
                continue
            qty_shop = s.quantity or 0
            sell_price = p.sell_price_per_item or 0.0
            shop_sell_uzs += qty_shop * sell_price

        # ---- 3) Fabric total value (UZS only) ----
        fabrics = Fabric.query.all()
        fabric_value_uzs = 0.0
        for f in fabrics:
            cur = (f.price_currency or "UZS").upper()
            if cur != "UZS":
                continue
            fabric_value_uzs += f.total_value()

        # ---- 4) Sales totals (reuse existing helper) ----
        totals = self.sales_totals()
        today_sales_uzs = totals["today"].get("UZS", 0.0)
        month_sales_uzs = totals["month"].get("UZS", 0.0)

        # ---- 5) Month profit (sum of sale.profit for current month, UZS) ----
        today = date.today()
        month_start = date(today.year, today.month, 1)
        month_sales = (
            Sale.query
            .filter(Sale.date >= month_start, Sale.date <= today)
            .all()
        )
        month_profit_uzs = 0.0
        for s in month_sales:
            cur = (s.currency or "UZS").upper()
            if cur != "UZS":
                continue
            month_profit_uzs += s.profit

        # ---- 5.5) Unrealized profit (potential profit in remaining stock) ----
        stock_profit_uzs, stock_profit_usd = self.stock_profit_totals()

        # ---- 5.6) Realized profit for all time (all sales, UZS only) ----
        all_sales = Sale.query.all()
        realized_profit_uzs = 0.0
        for s in all_sales:
            cur = (s.currency or "UZS").upper()
            if cur != "UZS":
                continue
            realized_profit_uzs += s.profit

        # ---- 6) Low stock products (factory + shop <= threshold) ----
        low_stock = []
        for p in products:
            shop_qty = p.shop_stock.quantity if p.shop_stock else 0
            total_qty = (p.quantity or 0) + (shop_qty or 0)
            if total_qty <= LOW_STOCK_THRESHOLD:
                low_stock.append(p)

        # ---- 7) Per-product breakdown for table ----
        product_rows = []
        for p in products:
            shop_qty = p.shop_stock.quantity if p.shop_stock else 0
            factory_qty = p.quantity or 0
            margin = (p.sell_price_per_item or 0.0) - (p.cost_price_per_item or 0.0)

            # potential profit in all current stock (factory + shop)
            potential_profit = (factory_qty + shop_qty) * margin

            # realized profit from all past sales of this product (in UZS)
            sold_units = 0
            realized_profit = 0.0
            for s in p.sales:
                sold_units += s.quantity
                cur = (s.currency or "UZS").upper()
                if cur != "UZS":
                    continue
                realized_profit += s.profit

            product_rows.append({
                "name": p.name,
                "factory_qty": factory_qty,
                "shop_qty": shop_qty,
                "cost_price": p.cost_price_per_item or 0.0,
                "sell_price": p.sell_price_per_item or 0.0,
                "potential_profit": potential_profit,
                "sold_units": sold_units,
                "realized_profit": realized_profit,
            })

        return {
            "factory_cost_uzs": factory_cost_uzs,
            "shop_sell_uzs": shop_sell_uzs,
            "fabric_value_uzs": fabric_value_uzs,
            "today_sales_uzs": today_sales_uzs,
            "month_sales_uzs": month_sales_uzs,
            "month_profit_uzs": month_profit_uzs,
            "unrealized_profit": stock_profit_uzs,
            "realized_profit": realized_profit_uzs,
            "low_stock": low_stock,
            "products": product_rows,
        }