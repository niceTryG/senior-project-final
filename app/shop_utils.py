from .extensions import db
from .models import Shop, ShopFactoryLink


def get_or_create_default_shop(factory_id: int) -> Shop:
    """
    Return the default shop for the given factory.

    Real factory-shop relationship is stored in ShopFactoryLink.
    Shop.factory_id is kept only as a legacy compatibility column because
    the current DB schema still requires shops.factory_id NOT NULL.
    """

    existing_link = (
        ShopFactoryLink.query
        .join(Shop, Shop.id == ShopFactoryLink.shop_id)
        .filter(
            ShopFactoryLink.factory_id == factory_id,
            Shop.name == "Main Shop",
        )
        .first()
    )

    if existing_link and existing_link.shop:
        return existing_link.shop

    shop = Shop(
        factory_id=factory_id,  # legacy compatibility for current DB schema
        name="Main Shop",
        location=None,
        note="Auto-created default shop",
        is_active=True,
    )
    db.session.add(shop)
    db.session.flush()

    link = ShopFactoryLink(
        shop_id=shop.id,
        factory_id=factory_id,
    )
    db.session.add(link)
    db.session.flush()

    return shop