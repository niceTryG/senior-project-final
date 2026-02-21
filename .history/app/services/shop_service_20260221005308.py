from typing import Optional, Dict, Any
from datetime import date, datetime
from sqlalchemy import or_
import csv
import io

from ..extensions import db
from ..models import (
    Product,
    ShopStock,
    Sale,
    ShopOrder,
    ShopOrderItem,
    Movement,
    StockMovement,
)


class ShopService:
    """Business logic for shop stock (магазин)."""

    # ---------- СПИСОК ТОВАРОВ В МАГАЗИНЕ ----------

    def list_items(
        self,
        q: Optional[str] = None,
        sort: str = "name",
        factory_id: Optional[int] = None,
    ) -> Dict[str, Any]:

        query = ShopStock.query.join(ShopStock.product)

        if factory_id is not None:
            query = query.filter(Product.factory_id == factory_id)

        if q:
            like_pattern = f"%{q}%"
            query = query.filter(
                or_(
                    Product.name.ilike(like_pattern),
                    Product.category.ilike(like_pattern),
                )
            )

        if sort == "name":
            query = query.order_by(Product.name.asc())
        elif sort == "category":
            query = query.order_by(
                Product.category.asc().nullslast(),
                Product.name.asc(),
            )
        elif sort == "qty_desc":
            query = query.order_by(ShopStock.quantity.desc())
        elif sort == "qty_asc":
            query = query.order_by(ShopStock.quantity.asc())
        else:
            query = query.order_by(Product.name.asc())

        items = query.all()

        total_qty = sum(item.quantity for item in items)
        total_value_uzs = sum(item.total_value for item in items)

        return {
            "items": items,
            "total_qty": total_qty,
            "total_value_uzs": total_value_uzs,
        }

    # ---------- ПЕРЕДАЧА С ФАБРИКИ В МАГАЗИН ----------

    def transfer_to_shop(
        self,
        product_id: int,
        quantity: int,
        sell_price_per_item: Optional[float] = None,
        created_by=None,
        factory_id: Optional[int] = None,
    ) -> ShopStock:

        if quantity <= 0:
            raise ValueError("Количество должно быть больше нуля.")

        product_query = Product.query.filter(Product.id == product_id)
        if factory_id is not None:
            product_query = product_query.filter(Product.factory_id == factory_id)

        product = product_query.first()

        if not product:
            raise ValueError("Товар не найден.")

        if product.quantity < quantity:
            raise ValueError("На фабрике недостаточно остатка для передачи.")

        if sell_price_per_item is not None:
            product.sell_price_per_item = sell_price_per_item

        shop_row = ShopStock.query.filter_by(product_id=product.id).first()
        if not shop_row:
            shop_row = ShopStock(product_id=product.id, quantity=0)
            db.session.add(shop_row)

        shop_row.quantity += quantity
        product.quantity -= quantity

        effective_factory_id = factory_id or product.factory_id

        mv = StockMovement(
            factory_id=effective_factory_id,
            product_id=product.id,
            qty_change=quantity,
            source="factory",
            destination="shop",
            movement_type="factory_to_shop",
            comment=f"Transferred {quantity} pcs to shop",
        )
        db.session.add(mv)

        move = Movement(
            factory_id=effective_factory_id,
            product_id=product.id,
            source="factory",
            destination="shop",
            change=quantity,
            note=f"Transferred {quantity} items to shop stock",
            created_by_id=created_by.id if created_by else None,
            timestamp=datetime.utcnow(),
        )
        db.session.add(move)

        db.session.commit()
        return shop_row

    # ---------- ПРОДАЖА ИЛИ ПРОДАЖА + ЗАКАЗ ----------

    def sell_from_shop_or_create_order(
        self,
        product_id: int,
        requested_qty: int,
        customer_name: Optional[str] = None,
        customer_phone: Optional[str] = None,
        note: Optional[str] = None,
        allow_partial_sale: bool = True,
        created_by=None,
        factory_id: Optional[int] = None,
    ) -> Dict[str, Any]:

        if requested_qty <= 0:
            raise ValueError("Количество должно быть больше нуля.")

        product_query = Product.query.filter(Product.id == product_id)
        if factory_id is not None:
            product_query = product_query.filter(Product.factory_id == factory_id)

        product = product_query.first()

        if not product:
            raise ValueError("Товар не найден.")

        stock_query = (
            ShopStock.query
            .join(Product)
            .filter(ShopStock.product_id == product_id)
        )

        if factory_id is not None:
            stock_query = stock_query.filter(Product.factory_id == factory_id)

        stock = stock_query.first()
        available = stock.quantity if stock else 0
        effective_factory_id = factory_id or product.factory_id

        sale_obj = None
        order_obj = None

        if requested_qty <= available and available > 0:
            sale_obj = Sale(
                product_id=product.id,
                date=date.today(),
                customer_name=customer_name,
                customer_phone=customer_phone,
                quantity=requested_qty,
                sell_price_per_item=product.sell_price_per_item or 0.0,
                cost_price_per_item=product.cost_price_per_item or 0.0,
                currency=product.currency or "UZS",
            )

            stock.quantity -= requested_qty
            db.session.add(sale_obj)

            stock_mv = StockMovement(
                factory_id=effective_factory_id,
                product_id=product.id,
                qty_change=-requested_qty,
                source="shop",
                destination="customer",
                movement_type="shop_sale",
                comment=f"Sold {requested_qty} items",
            )
            db.session.add(stock_mv)

            db.session.commit()

            return {
                "sale": sale_obj,
                "order": None,
                "missing": 0,
                "sold_now": requested_qty,
                "available_before": available,
            }

        missing = max(requested_qty - available, 0)
        sold_now = 0

        order_obj = ShopOrder(
            factory_id=effective_factory_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            note=note,
            status="pending",
            created_by=created_by,
        )

        item = ShopOrderItem(
            order=order_obj,
            product=product,
            qty_requested=requested_qty,
            qty_from_shop_now=sold_now,
            qty_remaining=missing,
        )

        db.session.add(order_obj)
        db.session.add(item)
        db.session.commit()

        return {
            "sale": sale_obj,
            "order": order_obj,
            "missing": missing,
            "sold_now": sold_now,
            "available_before": available,
        }

    # ---------- EXPORT ITEMS CSV (EXCEL SAFE) ----------

    def export_items_csv(
        self,
        q: Optional[str] = None,
        sort: str = "name",
        factory_id: Optional[int] = None,
    ) -> bytes:
        """
        Excel-safe CSV export.
        Uses UTF-16LE with BOM so Windows Excel opens correctly.
        """

        data = self.list_items(q=q, sort=sort, factory_id=factory_id)
        items = data["items"]

        output = io.StringIO()
        writer = csv.writer(output, delimiter=",", lineterminator="\r\n")

        writer.writerow(["sep=,"])
        writer.writerow(["ID", "Name", "Category", "Quantity in shop", "Total value (UZS)"])

        for row in items:
            product = row.product
            writer.writerow(
                [
                    product.id,
                    product.name,
                    product.category or "",
                    row.quantity,
                    row.total_value,
                ]
            )

        text = output.getvalue()
        output.close()

        # UTF-16LE with BOM
        return b"\xff\xfe" + text.encode("utf-16le")