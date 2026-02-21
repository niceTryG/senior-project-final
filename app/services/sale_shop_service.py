from datetime import date
from ..models import Product, Sale, ShopOrder, ShopOrderItem
from ..extensions import db

class SaleShopService:

    def sell_or_order(self, product_id, requested_qty, created_by):

        product = Product.query.get(product_id)

        # if shop has enough stock → sell immediately
        if product.shop_stock and product.shop_stock.quantity >= requested_qty:
            product.shop_stock.quantity -= requested_qty
            sale = Sale(
                product_id = product.id,
                quantity=requested_qty,
                sell_price_per_item=product.sell_price_per_item,
                cost_price_per_item=product.cost_price_per_item,
                currency=product.currency,
                created_by_id=created_by.id,
            )
            db.session.add(sale)
            db.session.commit()
            return {"sold_now": requested_qty, "missing": 0}

        # if not enough in shop → create order
        missing_qty = requested_qty

        order = ShopOrder(
            date=date.today(),
            customer_name=None,
            customer_phone=None,
            status="pending",
            created_by_id=created_by.id,
        )
        db.session.add(order)
        db.session.flush()

        order_item = ShopOrderItem(
            order_id=order.id,
            product_id=product.id,
            qty_requested=requested_qty,
            qty_from_shop_now=0,
            qty_remaining=requested_qty,
        )
        db.session.add(order_item)
        db.session.commit()

        return {"sold_now": 0, "missing": missing_qty}
