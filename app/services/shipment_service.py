# services/shipment_service.py
from app import db
from app.models import FactoryStock, ShopStock, ShopOrderItem, Order, OrderStatus
from .movement_service import log_movement

def ship_to_shop(*, product, ship_qty: int, dad_user, shop):
    """
    Dad ships finished products from factory to shop.
    Auto-allocates to pending orders for this product.
    """

    factory_stock = (
        FactoryStock.query
        .filter_by(product_id=product.id)
        .with_for_update()
        .first()
    )
    if not factory_stock or factory_stock.qty < ship_qty:
        raise ValueError("Not enough factory stock")

    # 1. Decrease factory stock
    factory_stock.qty -= ship_qty

    # 2. Increase shop stock
    shop_stock = (
        ShopStock.query
        .filter_by(product_id=product.id, shop_id=shop.id)
        .with_for_update()
        .first()
    )
    if not shop_stock:
        shop_stock = ShopStock(product_id=product.id, shop_id=shop.id, qty=0)
        db.session.add(shop_stock)
    shop_stock.qty += ship_qty

    # 3. Log movement
    log_movement(
        product_id=product.id,
        qty=ship_qty,
        from_location="factory",
        to_location="shop",
        movement_type="FACTORY_TO_SHOP",
        user_id=dad_user.id,
    )

    # 4. Allocate shipped qty to pending orders for this product
    remaining_to_allocate = ship_qty
    pending_items = (
        ShopOrderItem.query
        .join(Order, Order.id == ShopOrderItem.order_id)
        .filter(
            ShopOrderItem.product_id == product.id,
            ShopOrderItem.qty_remaining > 0,
            Order.status == OrderStatus.PENDING_PRODUCTION.value,
        )
        .order_by(Order.created_at.asc())
        .with_for_update()
        .all()
    )

    for item in pending_items:
        if remaining_to_allocate <= 0:
            break

        alloc = min(item.qty_remaining, remaining_to_allocate)
        item.qty_remaining -= alloc
        item.qty_from_shop_now += alloc
        remaining_to_allocate -= alloc

        # If this order is now fully satisfied from shop point of view:
        if item.qty_remaining == 0:
            _update_order_status_if_ready(item.order)

    db.session.commit()


def _update_order_status_if_ready(order: Order):
    # If all items have qty_remaining == 0 but not yet delivered to customer:
    if all(i.qty_remaining == 0 for i in order.shop_order_items):
        order.status = OrderStatus.READY_FOR_DELIVERY.value
