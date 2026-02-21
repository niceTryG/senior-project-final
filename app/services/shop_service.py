from typing import Optional, Dict, Any
from datetime import date, datetime
from sqlalchemy import or_
import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

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

    # ---------- ВСПОМОГАТЕЛЬНОЕ: СКОЛЬКО В МАГАЗИНЕ ----------

    def get_stock_quantity(
        self,
        product_id: int,
        factory_id: Optional[int] = None,
    ) -> int:
        query = (
            ShopStock.query
            .join(Product)
            .filter(ShopStock.product_id == product_id)
        )
        if factory_id is not None:
            query = query.filter(Product.factory_id == factory_id)

        stock = query.first()
        return stock.quantity if stock else 0

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

        sale_obj: Optional[Sale] = None
        order_obj: Optional[ShopOrder] = None

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

            stock.quantity = available - requested_qty
            db.session.add(sale_obj)
            if stock:
                db.session.add(stock)

            move = Movement(
                factory_id=effective_factory_id,
                product_id=product.id,
                source="shop",
                destination="customer",
                change=-requested_qty,
                note=f"Sold {requested_qty} items from shop to customer {customer_name or ''}",
                created_by_id=created_by.id if created_by else None,
                timestamp=datetime.utcnow(),
            )
            db.session.add(move)

            stock_mv = StockMovement(
                factory_id=effective_factory_id,
                product_id=product.id,
                qty_change=-requested_qty,
                source="shop",
                destination="customer",
                movement_type="shop_sale",
                comment=f"Sold {requested_qty} items to customer {customer_name or ''}".strip(),
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

        if allow_partial_sale and available > 0:
            sale_obj = Sale(
                product_id=product.id,
                date=date.today(),
                customer_name=customer_name,
                customer_phone=customer_phone,
                quantity=available,
                sell_price_per_item=product.sell_price_per_item or 0.0,
                cost_price_per_item=product.cost_price_per_item or 0.0,
                currency=product.currency or "UZS",
            )
            sold_now = available

            if stock:
                stock.quantity = 0

            move = Movement(
                factory_id=effective_factory_id,
                product_id=product.id,
                source="shop",
                destination="customer(partial)",
                change=-sold_now,
                note=f"Sold {sold_now} items (partial) to customer {customer_name or ''}",
                created_by_id=created_by.id if created_by else None,
                timestamp=datetime.utcnow(),
            )
            db.session.add(move)

            stock_mv = StockMovement(
                factory_id=effective_factory_id,
                product_id=product.id,
                qty_change=-sold_now,
                source="shop",
                destination="customer",
                movement_type="shop_sale",
                comment=f"Partial sale {sold_now} pcs to customer {customer_name or ''}".strip(),
            )
            db.session.add(stock_mv)

            db.session.add(sale_obj)
            if stock:
                db.session.add(stock)

        order_obj = ShopOrder(
            factory_id=factory_id,
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

        move = Movement(
            factory_id=effective_factory_id,
            product_id=product.id,
            source="shop",
            destination="order",
            change=+missing,
            note=f"Created production order for {missing} items",
            created_by_id=created_by.id if created_by else None,
            timestamp=datetime.utcnow(),
        )
        db.session.add(move)

        db.session.add(order_obj)
        db.session.add(item)
        db.session.commit()

        if available > 0:
            covered = requested_qty - missing
            if covered > 0:
                reserve_move = Movement(
                    factory_id=effective_factory_id,
                    product_id=product.id,
                    source="shop",
                    destination="reserved(order covered)",
                    change=0,
                    note=f"{covered} items reserved to cover old pending orders",
                    created_by_id=created_by.id if created_by else None,
                    timestamp=datetime.utcnow(),
                )
                db.session.add(reserve_move)
                db.session.commit()

        return {
            "sale": sale_obj,
            "order": order_obj,
            "missing": missing,
            "sold_now": sold_now,
            "available_before": available,
        }

    # ---------- EXPORT: ONE XLSX WITH 2 SHEETS ----------

    def export_full_report_xlsx(
        self,
        q: Optional[str] = None,
        sort: str = "name",
        factory_id: Optional[int] = None,
        report_day: Optional[date] = None,
    ) -> bytes:
        """
        Generates ONE Excel file with 2 sheets:
          1) Shop stock
          2) Daily report (sales summary for the day)
        """
        if factory_id is None:
            raise ValueError("factory_id is required for XLSX export")

        day = report_day or date.today()

        # ---------- sheet 1 data ----------
        stock_data = self.list_items(q=q, sort=sort, factory_id=factory_id)
        items = stock_data["items"]
        total_qty = stock_data["total_qty"]
        total_value_uzs = stock_data["total_value_uzs"]

        # ---------- sheet 2 data (sales summary for day) ----------
        sales = (
            Sale.query
            .join(Product, Product.id == Sale.product_id)
            .filter(Product.factory_id == factory_id)
            .filter(Sale.date == day)
            .all()
        )

        sales_count = len(sales)

        def _safe(v):
            try:
                return float(v or 0)
            except Exception:
                return 0.0

        total_sell = 0.0
        total_cost = 0.0
        for s in sales:
            if getattr(s, "total_sell", None) is not None:
                total_sell += _safe(s.total_sell)
            else:
                total_sell += _safe(s.quantity) * _safe(s.sell_price_per_item)

            if getattr(s, "total_cost", None) is not None:
                total_cost += _safe(s.total_cost)
            else:
                total_cost += _safe(s.quantity) * _safe(s.cost_price_per_item)

        profit = total_sell - total_cost

        # ---------- create workbook ----------
        wb = Workbook()

        # Styles
        header_fill = PatternFill("solid", fgColor="111827")
        header_font = Font(bold=True, color="FFFFFF")
        header_align = Alignment(horizontal="center", vertical="center")
        bold_font = Font(bold=True)

        # ===== Sheet 1: Shop stock =====
        ws = wb.active
        ws.title = "Shop stock"

        headers = ["ID", "Name", "Category", "Quantity in shop", "Total value (UZS)"]
        ws.append(headers)

        ws.row_dimensions[1].height = 22
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align

        for row in items:
            p = row.product
            ws.append(
                [
                    p.id,
                    p.name,
                    p.category or "",
                    row.quantity,
                    row.total_value,
                ]
            )

        # Totals row
        ws.append(["", "TOTAL", "", total_qty, total_value_uzs])
        total_row_idx = ws.max_row
        for col in range(1, 6):
            ws.cell(row=total_row_idx, column=col).font = bold_font

        ws.freeze_panes = "A2"

        # Auto column width
        for col_cells in ws.columns:
            max_length = 0
            col_letter = col_cells[0].column_letter
            for c in col_cells:
                if c.value is not None:
                    max_length = max(max_length, len(str(c.value)))
            ws.column_dimensions[col_letter].width = min(max_length + 2, 48)

        # ===== Sheet 2: Daily report =====
        ws2 = wb.create_sheet("Daily report")

        ws2["A1"] = "Mini Moda — Daily report"
        ws2["A1"].font = Font(bold=True, size=14)

        ws2["A2"] = f"Date: {day.isoformat()}"
        ws2["A2"].font = Font(bold=True)

        ws2.append([])
        ws2.append(["Sales block"])
        ws2["A4"].font = bold_font

        ws2.append(["Sales count", sales_count])
        ws2.append(["Total revenue", total_sell])
        ws2.append(["Total cost", total_cost])
        ws2.append(["Profit", profit])

        ws2.column_dimensions["A"].width = 28
        ws2.column_dimensions["B"].width = 20

        # Make labels a bit nicer
        for r in range(5, 9):
            ws2[f"A{r}"].font = Font(bold=True)
            ws2[f"A{r}"].alignment = Alignment(horizontal="left")
            ws2[f"B{r}"].alignment = Alignment(horizontal="right")

        # Output bytes
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.read()