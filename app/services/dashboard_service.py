# services/dashboard_service.py
from sqlalchemy import func
from datetime import datetime, date
from app import db
from app.models import FactoryStock, ShopStock, Order, ShopOrderItem, Movement, OrderStatus

def get_owner_dashboard_data():
    # totals
    factory_total = (
        db.session.query(func.sum(FactoryStock.qty))
        .scalar() or 0
    )
    shop_total = (
        db.session.query(func.sum(ShopStock.qty))
        .scalar() or 0
    )

    pending_orders = (
        Order.query.filter_by(status=OrderStatus.PENDING_PRODUCTION.value)
        .order_by(Order.created_at.asc())
        .limit(20)
        .all()
    )

    ready_orders = (
        Order.query.filter_by(status=OrderStatus.READY_FOR_DELIVERY.value)
        .order_by(Order.created_at.asc())
        .limit(20)
        .all()
    )

    recent_movements = (
        Movement.query
        .order_by(Movement.created_at.desc())
        .limit(20)
        .all()
    )

    return {
        "factory_total": factory_total,
        "shop_total": shop_total,
        "pending_orders": pending_orders,
        "ready_orders": ready_orders,
        "recent_movements": recent_movements,
    }


def get_uncle_dashboard_data(uncle, shop):
    shop_stock_items = (
        ShopStock.query
        .filter_by(shop_id=shop.id)
        .order_by(ShopStock.qty.desc())
        .all()
    )

    my_orders = (
        Order.query
        .filter_by(created_by_id=uncle.id)
        .order_by(Order.created_at.desc())
        .limit(20)
        .all()
    )

    today_sales_count = (
        Movement.query
        .filter_by(
            movement_type="SHOP_SALE",
            user_id=uncle.id,
        )
        .filter(Movement.created_at >= date.today())
        .count()
    )

    low_stock = (
        ShopStock.query
        .filter_by(shop_id=shop.id)
        .filter(ShopStock.qty < 5)
        .order_by(ShopStock.qty.asc())
        .all()
    )

    return {
        "shop_stock_items": shop_stock_items,
        "my_orders": my_orders,
        "today_sales_count": today_sales_count,
        "low_stock": low_stock,
    }
