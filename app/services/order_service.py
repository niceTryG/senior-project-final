# services/order_service.py
from app import db
from app.models import ShopStock, ShopOrderItem, Order, OrderStatus
from .movement_service import log_movement

def process_shop_sale(*, product, qty_requested: int, shop, customer_name: str | None, uncle):
    """
    Returns: (order, qty_from_shop_now, qty_remaining)
    """
    # 1. Read current shop stock
    shop_stock = (
        ShopStock.query
        .filter_by(shop_id=shop.id, product_id=product.id)
        .with_for_update()
        .first()
    )

    available = shop_stock.qty if shop_stock else 0
    qty_from_shop_now = min(available, qty_requested)
    qty_remaining = qty_requested - qty_from_shop_now

    # 2. Decrease stock and log movement for the part sold now
    order = Order(
        customer_name=customer_name,
        created_by_id=uncle.id,
    )
    db.session.add(order)

    if qty_from_shop_now > 0:
        shop_stock.qty -= qty_from_shop_now
        log_movement(
            product_id=product.id,
            qty=qty_from_shop_now,
            from_location="shop",
            to_location="customer",
            movement_type="SHOP_SALE",
            user_id=uncle.id,
            order_id=order.id,
        )

    # 3. Create ShopOrderItem (production request)
    shop_order_item = ShopOrderItem(
        order_id=order.id,
        product_id=product.id,
        qty_requested=qty_requested,
        qty_from_shop_now=qty_from_shop_now,
        qty_remaining=qty_remaining,
    )
    db.session.add(shop_order_item)

    # 4. Set order status
    if qty_remaining == 0:
        order.status = OrderStatus.COMPLETED.value
    else:
        order.status = OrderStatus.PENDING_PRODUCTION.value

    db.session.commit()
    return order, qty_from_shop_now, qty_remaining
