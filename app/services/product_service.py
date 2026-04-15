from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import or_, func, text

from ..extensions import db
from ..models import Product, Sale, CashRecord, Production, ShopStock, Fabric, StockMovement
from ..shop_utils import get_or_create_default_shop


LOW_STOCK_THRESHOLD = 20  # you can change this later or move to settings


class ProductService:
    def list_products(
        self,
        query: str | None = None,
        category: str | None = None,
        factory_id: int | None = None,
    ):
        q = Product.query
        if factory_id is not None:
            q = q.filter(Product.factory_id == factory_id)

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

    def get_categories(self, factory_id: int | None = None):
        q = db.session.query(Product.category).filter(
            Product.category.isnot(None),
            Product.category != "",
        )
        if factory_id is not None:
            q = q.filter(Product.factory_id == factory_id)

        rows = q.distinct().order_by(Product.category.asc()).all()
        return [r[0] for r in rows]

    def add_product(
        self,
        factory_id: int,
        name: str,
        category: str | None,
        quantity: int,
        cost_price_per_item: float | None,
        sell_price_per_item: float | None,
        currency: str,
        image_path=None,
        website_image=None,
        fabric_used=None,
        notes=None,
    ):
        name_clean = name.strip()
        category_clean = (category or "").strip()
        fabric_used_clean = (fabric_used or "").strip() or None
        notes_clean = (notes or "").strip() or None
        qty = max(quantity, 0)

        existing = Product.query.filter(
            Product.factory_id == factory_id,
            db.func.lower(Product.name) == name_clean.lower(),
            db.func.lower(db.func.coalesce(Product.category, "")) == category_clean.lower(),
            Product.currency == currency,
        ).first()

        if existing:
            old_qty = existing.quantity or 0
            new_qty = qty

            existing.quantity = old_qty + new_qty

            if new_qty > 0 and cost_price_per_item is not None:
                old_cost = existing.cost_price_per_item or 0.0
                new_cost = cost_price_per_item

                total_cost_old = old_cost * old_qty
                total_cost_new = new_cost * new_qty
                total_qty = old_qty + new_qty

                if total_qty > 0:
                    existing.cost_price_per_item = (
                        total_cost_old + total_cost_new
                    ) / total_qty

            if sell_price_per_item is not None and sell_price_per_item > 0:
                existing.sell_price_per_item = sell_price_per_item

            if image_path is not None:
                existing.image_path = image_path

            if website_image is not None:
                existing.website_image = website_image

            existing.fabric_used = fabric_used_clean
            existing.notes = notes_clean

            if new_qty > 0:
                prod = Production(
                    product_id=existing.id,
                    quantity=new_qty,
                    note=None,
                )
                db.session.add(prod)

            db.session.commit()
            return existing

        product = Product(
            factory_id=factory_id,
            name=name_clean,
            category=category_clean or None,
            quantity=qty,
            cost_price_per_item=cost_price_per_item or 0.0,
            sell_price_per_item=sell_price_per_item or 0.0,
            currency=currency,
            image_path=image_path,
            website_image=website_image,
            fabric_used=fabric_used_clean,
            notes=notes_clean,
        )
        db.session.add(product)
        db.session.flush()

        if qty > 0:
            prod = Production(
                product_id=product.id,
                quantity=qty,
                note=None,
            )
            db.session.add(prod)

        db.session.commit()
        return product

    def increase_stock(self, factory_id: int, product_id: int, quantity: int):
        product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
        if not product or quantity <= 0:
            return False
        product.quantity += quantity
        db.session.commit()
        return True

    def sell_product(
        self,
        factory_id: int,
        product_id: int,
        quantity: int,
        customer_name: str | None = None,
        customer_phone: str | None = None,
        sell_price_override: float | None = None,
    ):
        product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
        if not product or quantity <= 0:
            return None

        shop_stock = self._get_or_create_shop_stock(product_id, factory_id)

        if quantity > shop_stock.quantity:
            return None

        sell_price = (
            sell_price_override
            if sell_price_override is not None
            else product.sell_price_per_item
        )
        cost_price = product.cost_price_per_item

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

        cash = CashRecord(
            date=date.today(),
            amount=sale.total_sell,
            currency=product.currency,
            note=f"Продажа {product.name} x{quantity} покупатель {customer_name or ''}",
            factory_id=factory_id,
        )

        db.session.add(sale)
        db.session.add(cash)
        db.session.commit()
        return sale

    def recent_sales(self, limit: int = 20, factory_id: int | None = None):
        q = Sale.query.join(Product)
        if factory_id is not None:
            q = q.filter(Product.factory_id == factory_id)

        return q.order_by(Sale.date.desc(), Sale.id.desc()).limit(limit).all()

    def total_stock_value(self, factory_id: int):
        rows = (
            db.session.execute(
                text(
                    """
                SELECT
                  COALESCE(SUM(CASE WHEN currency = 'UZS' THEN quantity * cost_price_per_item ELSE 0 END), 0) AS total_uzs,
                  COALESCE(SUM(CASE WHEN currency = 'USD' THEN quantity * cost_price_per_item ELSE 0 END), 0) AS total_usd
                FROM products
                WHERE factory_id = :factory_id
            """
                ),
                {"factory_id": factory_id},
            )
            .mappings()
            .first()
        )

        total_uzs = float(rows["total_uzs"] or 0)
        total_usd = float(rows["total_usd"] or 0)
        return total_uzs, total_usd

    def sales_totals(self, factory_id: int | None = None):
        today = date.today()
        yesterday = today - timedelta(days=1)

        weekday = today.weekday()
        this_monday = today - timedelta(days=weekday)
        last_monday = this_monday - timedelta(days=7)
        last_sunday = this_monday - timedelta(days=1)

        month_start = date(today.year, today.month, 1)

        base_q = Sale.query.join(Product)
        if factory_id is not None:
            base_q = base_q.filter(Product.factory_id == factory_id)

        today_sales = base_q.filter(Sale.date == today).all()
        yesterday_sales = base_q.filter(Sale.date == yesterday).all()
        last_week_sales = base_q.filter(
            Sale.date >= last_monday,
            Sale.date <= last_sunday,
        ).all()
        month_sales = base_q.filter(
            Sale.date >= month_start,
            Sale.date <= today,
        ).all()

        def sum_by_currency(sales_list):
            totals = {}
            for s in sales_list:
                cur = (s.currency or "UZS").upper()
                totals.setdefault(cur, 0.0)
                totals[cur] += s.total_sell
            return totals

        return {
            "today": sum_by_currency(today_sales),
            "yesterday": sum_by_currency(yesterday_sales),
            "last_week": sum_by_currency(last_week_sales),
            "month": sum_by_currency(month_sales),
            "last_week_range": (last_monday, last_sunday),
        }

    def list_sales(
        self,
        date_from=None,
        date_to=None,
        factory_id: int | None = None,
    ):
        q = Sale.query.join(Product)
        if factory_id is not None:
            q = q.filter(Product.factory_id == factory_id)

        if date_from:
            q = q.filter(Sale.date >= date_from)
        if date_to:
            q = q.filter(Sale.date <= date_to)

        return q.order_by(Sale.date.desc(), Sale.id.desc()).all()

    def production_stats(self, factory_id: int | None = None):
        q_all = db.session.query(func.coalesce(func.sum(Production.quantity), 0)).join(
            Product
        )
        q_today = db.session.query(
            func.coalesce(func.sum(Production.quantity), 0)
        ).join(Product)

        if factory_id is not None:
            q_all = q_all.filter(Product.factory_id == factory_id)
            q_today = q_today.filter(Product.factory_id == factory_id)

        total_all = q_all.scalar()
        total_today = q_today.filter(Production.date == date.today()).scalar()

        return {
            "total_all": total_all or 0,
            "total_today": total_today or 0,
        }

    def stock_value_sell_totals(self, factory_id: int | None = None):
        q = Product.query
        if factory_id is not None:
            q = q.filter(Product.factory_id == factory_id)

        products = q.all()
        total_uzs = 0.0
        total_usd = 0.0

        for p in products:
            value = p.stock_value_sell()
            if (p.currency or "UZS").upper() == "USD":
                total_usd += value
            else:
                total_uzs += value

        return total_uzs, total_usd

    def stock_profit_totals(self, factory_id: int | None = None):
        q = Product.query
        if factory_id is not None:
            q = q.filter(Product.factory_id == factory_id)

        products = q.all()
        total_uzs = 0.0
        total_usd = 0.0

        for p in products:
            profit = p.stock_profit()
            if (p.currency or "UZS").upper() == "USD":
                total_usd += profit
            else:
                total_uzs += profit

        return total_uzs, total_usd

    def get_low_stock_products(self, factory_id: int | None = None):
        q = Product.query
        if factory_id is not None:
            q = q.filter(Product.factory_id == factory_id)

        return (
            q.filter(Product.quantity <= LOW_STOCK_THRESHOLD)
            .order_by(Product.quantity.asc())
            .all()
        )

    def _get_or_create_shop_stock(self, product_id: int, factory_id: int) -> ShopStock:
        default_shop = get_or_create_default_shop(factory_id)

        stock = (
            ShopStock.query.filter(
                ShopStock.product_id == product_id,
                ShopStock.shop_id == default_shop.id,
                ShopStock.source_factory_id == factory_id,
            )
            .first()
        )
        if not stock:
            stock = ShopStock(
                shop_id=default_shop.id,
                product_id=product_id,
                source_factory_id=factory_id,
                quantity=0,
            )
            db.session.add(stock)
            db.session.flush()
        return stock

    def transfer_to_shop(self, factory_id: int, product_id: int, quantity: int, user_id: int = None):
        """Move ready products from factory stock to shop stock, lock transfer price/value."""
        product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
        if not product or quantity <= 0:
            return None

        if quantity > product.quantity:
            return None

        # Use factory_transfer_price if set, else fallback to cost_price_per_item
        transfer_price = product.factory_transfer_price if product.factory_transfer_price is not None else product.cost_price_per_item
        currency = product.currency or "UZS"
        total_value = float(transfer_price or 0.0) * quantity

        product.quantity -= quantity
        shop_stock = self._get_or_create_shop_stock(product_id, factory_id)
        shop_stock.quantity += quantity

        # Lock transfer value in StockMovement
        movement = StockMovement(
            factory_id=factory_id,
            product_id=product_id,
            qty_change=-quantity,
            unit_price=transfer_price,
            total_value=total_value,
            currency=currency,
            locked_unit_price=transfer_price,
            locked_total_value=total_value,
            movement_type="factory_to_shop",
            source="factory",
            destination="shop",
            comment=f"Transfer to shop, locked at {transfer_price} {currency}",
        )
        db.session.add(movement)
        db.session.commit()
        return shop_stock

    def create_production(
        self,
        product_id: int,
        quantity: int,
        qty_issued_to_workers: int = None,
        qty_finished_good: int = None,
        qty_defective: int = None,
        qty_unfinished: int = None,
        qty_payable: int = None,
        shortfall_reason: str = None,
        note: str = None,
    ):
        """Create a production record with full accountability fields."""
        prod = Production(
            product_id=product_id,
            quantity=quantity,
            qty_issued_to_workers=qty_issued_to_workers,
            qty_finished_good=qty_finished_good,
            qty_defective=qty_defective,
            qty_unfinished=qty_unfinished,
            qty_payable=qty_payable,
            shortfall_reason=shortfall_reason,
            note=note,
        )
        db.session.add(prod)
        db.session.commit()
        return prod

    def list_shop_stock(
        self,
        query: str | None = None,
        sort: str = "name_asc",
        factory_id: int | None = None,
    ):
        q = ShopStock.query.join(Product)
        if factory_id is not None:
            q = q.filter(ShopStock.source_factory_id == factory_id)

        if query:
            pattern = f"%{query.lower()}%"
            q = q.filter(
                db.func.lower(Product.name).like(pattern)
                | db.func.lower(db.func.coalesce(Product.category, "")).like(pattern)
            )

        if sort == "name_desc":
            q = q.order_by(Product.name.desc())
        elif sort == "qty_asc":
            q = q.order_by(ShopStock.quantity.asc())
        elif sort == "qty_desc":
            q = q.order_by(ShopStock.quantity.desc())
        elif sort == "value_desc":
            q = q.order_by(
                (
                    ShopStock.quantity
                    * db.func.coalesce(Product.sell_price_per_item, 0)
                ).desc()
            )
        else:
            q = q.order_by(Product.name.asc())

        return q.all()

    def shop_stock_totals(self, factory_id: int | None = None):
        """Total money currently in shop (unsold goods), by currency."""
        q = ShopStock.query.join(Product)
        if factory_id is not None:
            q = q.filter(ShopStock.source_factory_id == factory_id)

        stocks = q.all()
        total_uzs = 0.0
        total_usd = 0.0

        for s in stocks:
            value = (s.quantity or 0) * (s.product.sell_price_per_item or 0)
            cur = (s.product.currency or "UZS").upper()
            if cur == "USD":
                total_usd += value
            else:
                total_uzs += value

        return total_uzs, total_usd

    def weekly_shop_report(self, factory_id: int | None = None):
        """Return weekly report for Monday–Sunday shop activity (current week)."""
        today = date.today()
        weekday = today.weekday()
        monday = today - timedelta(days=weekday)
        sunday = monday + timedelta(days=6)

        shop_q = ShopStock.query.join(Product)
        if factory_id is not None:
            shop_q = shop_q.filter(ShopStock.source_factory_id == factory_id)
        shop = shop_q.all()

        report = []

        for item in shop:
            product = item.product

            sales_q = Sale.query.filter(
                Sale.product_id == product.id,
                Sale.date >= monday,
                Sale.date <= sunday,
            )

            if factory_id is not None:
                sales_q = sales_q.join(Product).filter(Product.factory_id == factory_id)

            sales = sales_q.all()

            sold_qty = sum(s.quantity for s in sales)
            sent_qty = item.quantity + sold_qty
            total_value = (item.quantity or 0) * (product.sell_price_per_item or 0)

            report.append(
                {
                    "product": product,
                    "sent": sent_qty,
                    "sold": sold_qty,
                    "remaining": item.quantity,
                    "total_value": total_value,
                }
            )

        total_sent = sum((r["sent"] or 0) * (r["product"].sell_price_per_item or 0) for r in report)
        total_sold = sum((r["sold"] or 0) * (r["product"].sell_price_per_item or 0) for r in report)
        total_remaining = sum(r["total_value"] for r in report)

        return {
            "monday": monday,
            "sunday": sunday,
            "rows": report,
            "total_sent": total_sent,
            "total_sold": total_sold,
            "total_remaining": total_remaining,
            "weekly_profit": total_sold,
        }

    def get_monthly_report(self, factory_id: int | None = None):
        today = date.today()
        month_start = date(today.year, today.month, 1)

        base = Sale.query.join(Product)
        if factory_id is not None:
            base = base.filter(Product.factory_id == factory_id)

        sales = base.filter(Sale.date >= month_start, Sale.date <= today).all()

        daily_totals = (
            db.session.query(
                Sale.date,
                func.sum(Sale.quantity * Sale.sell_price_per_item).label("total"),
            )
            .join(Product)
            .filter(
                Sale.date >= month_start,
                Sale.date <= today,
                *([Product.factory_id == factory_id] if factory_id is not None else []),
            )
            .group_by(Sale.date)
            .order_by(Sale.date.asc())
            .all()
        )

        top_products = (
            db.session.query(
                Product.name,
                func.sum(Sale.quantity).label("qty"),
            )
            .join(Sale)
            .filter(
                Sale.date >= month_start,
                Sale.date <= today,
                *([Product.factory_id == factory_id] if factory_id is not None else []),
            )
            .group_by(Product.id)
            .order_by(func.sum(Sale.quantity).desc())
            .limit(10)
            .all()
        )

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

    def _get_total_shop_qty_for_product(
        self, product_id: int, factory_id: int | None = None
    ) -> int:
        q = db.session.query(func.coalesce(func.sum(ShopStock.quantity), 0)).filter(
            ShopStock.product_id == product_id
        )

        if factory_id is not None:
            q = q.filter(ShopStock.source_factory_id == factory_id)

        return int(q.scalar() or 0)

    def get_manager_financial_report(self, factory_id: int | None = None):
        """Full financial overview for manager (Dad). All values in UZS only."""

        q_products = Product.query
        if factory_id is not None:
            q_products = q_products.filter(Product.factory_id == factory_id)
        products = q_products.all()

        factory_cost_uzs = 0.0
        for p in products:
            cur = (p.currency or "UZS").upper()
            if cur != "UZS":
                continue
            qty_factory = p.quantity or 0
            cost_price = p.cost_price_per_item or 0.0
            factory_cost_uzs += qty_factory * cost_price

        q_shop = ShopStock.query.join(Product)
        if factory_id is not None:
            q_shop = q_shop.filter(ShopStock.source_factory_id == factory_id)
        shop_items = q_shop.all()

        shop_sell_uzs = 0.0
        for s in shop_items:
            p = s.product
            if not p:
                continue
            cur = (p.currency or "UZS").upper()
            if cur != "UZS":
                continue
            qty_shop = s.quantity or 0
            sell_price = p.sell_price_per_item or 0.0
            shop_sell_uzs += qty_shop * sell_price

        q_fabrics = Fabric.query
        if factory_id is not None:
            q_fabrics = q_fabrics.filter(Fabric.factory_id == factory_id)
        fabrics = q_fabrics.all()

        fabric_value_uzs = 0.0
        for f in fabrics:
            cur = (f.price_currency or "UZS").upper()
            if cur != "UZS":
                continue
            fabric_value_uzs += f.total_value() or 0.0

        totals = self.sales_totals(factory_id=factory_id)
        today_sales_uzs = totals.get("today", {}).get("UZS", 0.0)
        month_sales_uzs = totals.get("month", {}).get("UZS", 0.0)

        today_dt = date.today()
        month_start = date(today_dt.year, today_dt.month, 1)

        month_q = Sale.query.join(Product).filter(
            Sale.date >= month_start,
            Sale.date <= today_dt,
        )
        if factory_id is not None:
            month_q = month_q.filter(Product.factory_id == factory_id)
        month_sales = month_q.all()

        month_profit_uzs = 0.0
        for s in month_sales:
            cur = (s.currency or "UZS").upper()
            if cur != "UZS":
                continue
            month_profit_uzs += s.profit or 0.0

        stock_profit_uzs, stock_profit_usd = self.stock_profit_totals(factory_id=factory_id)

        all_q = Sale.query.join(Product)
        if factory_id is not None:
            all_q = all_q.filter(Product.factory_id == factory_id)
        all_sales = all_q.all()

        realized_profit_uzs = 0.0
        for s in all_sales:
            cur = (s.currency or "UZS").upper()
            if cur != "UZS":
                continue
            realized_profit_uzs += s.profit or 0.0

        low_stock = []
        for p in products:
            shop_qty = self._get_total_shop_qty_for_product(p.id, factory_id=factory_id)
            total_qty = (p.quantity or 0) + (shop_qty or 0)
            if total_qty <= LOW_STOCK_THRESHOLD:
                low_stock.append(p)

        product_rows = []
        for p in products:
            shop_qty = self._get_total_shop_qty_for_product(p.id, factory_id=factory_id) or 0
            factory_qty = p.quantity or 0
            margin = (p.sell_price_per_item or 0.0) - (p.cost_price_per_item or 0.0)

            potential_profit = (factory_qty + shop_qty) * margin

            sold_units = 0
            realized_profit = 0.0

            for s in p.sales:
                if factory_id is not None and getattr(p, "factory_id", None) != factory_id:
                    continue

                sold_units += s.quantity or 0

                cur = (s.currency or "UZS").upper()
                if cur != "UZS":
                    continue

                realized_profit += s.profit or 0.0

            product_rows.append(
                {
                    "name": p.name,
                    "factory_qty": factory_qty,
                    "shop_qty": shop_qty,
                    "cost_price": p.cost_price_per_item or 0.0,
                    "sell_price": p.sell_price_per_item or 0.0,
                    "potential_profit": potential_profit,
                    "sold_units": sold_units,
                    "realized_profit": realized_profit,
                }
            )

        return SimpleNamespace(
            factory_cost_uzs=factory_cost_uzs,
            shop_sell_uzs=shop_sell_uzs,
            fabric_value_uzs=fabric_value_uzs,
            today_sales_uzs=today_sales_uzs,
            month_sales_uzs=month_sales_uzs,
            month_profit_uzs=month_profit_uzs,
            stock_profit_uzs=stock_profit_uzs or 0.0,
            stock_profit_usd=stock_profit_usd or 0.0,
            realized_profit_uzs=realized_profit_uzs,
            transferred_to_shop_uzs=shop_sell_uzs,
            sold_uzs=month_sales_uzs,
            remaining_uzs=(factory_cost_uzs + fabric_value_uzs),
            profit_uzs=month_profit_uzs,
            low_stock=low_stock,
            product_rows=product_rows,
        )

    def production_summary(
        self,
        date_from=None,
        date_to=None,
        factory_id: int | None = None,
    ):
        q = Production.query.join(Product)
        if factory_id is not None:
            q = q.filter(Product.factory_id == factory_id)

        if date_from:
            q = q.filter(Production.date >= date_from)
        if date_to:
            q = q.filter(Production.date <= date_to)

        rows = q.all()

        stats = {}
        for r in rows:
            p = r.product
            if not p:
                continue
            key = p.id
            if key not in stats:
                stats[key] = {
                    "product": p,
                    "total_qty": 0,
                }
            stats[key]["total_qty"] += r.quantity

        total_qty = sum(r["total_qty"] for r in stats.values())

        return {
            "rows": list(stats.values()),
            "total_qty": total_qty,
        }

    def update_product_info(
        self,
        factory_id: int,
        product_id: int,
        category: str | None = None,
        fabric_used: str | None = None,
        notes: str | None = None,
        image_path: str | None = None,
        website_image: str | None = None,
    ):
        product = Product.query.filter(
            Product.id == product_id,
            Product.factory_id == factory_id,
        ).first()

        if not product:
            return None

        product.category = (category or "").strip() or None
        product.fabric_used = (fabric_used or "").strip() or None
        product.notes = (notes or "").strip() or None

        if image_path is not None:
            product.image_path = image_path

        if website_image is not None:
            product.website_image = website_image

        db.session.commit()
        return product