# services/movement_service.py
from app import db
from app.models import Movement

def log_movement(
    product_id: int,
    qty: int,
    from_location: str,
    to_location: str,
    movement_type: str,
    user_id: int | None = None,
    order_id: int | None = None,
):
    movement = Movement(
        product_id=product_id,
        qty=qty,
        from_location=from_location,     # "factory", "shop", "customer"
        to_location=to_location,
        movement_type=movement_type,     # "FACTORY_TO_SHOP", "SHOP_SALE", "ADJUSTMENT"
        user_id=user_id,
        order_id=order_id,
    )
    db.session.add(movement)
    # do NOT commit here – call from service that already controls transaction
