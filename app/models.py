from datetime import datetime, date, timedelta
import uuid
import secrets

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db


# ==========================
#   🏭 FACTORY (TENANT)
# ==========================


class Factory(db.Model):
    __tablename__ = "factories"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(128), nullable=False)
    location = db.Column(db.String(128))
    owner_name = db.Column(db.String(128))
    phone = db.Column(db.String(64))
    note = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # relations
    realizatsiya_settlements_received = db.relationship(
        "RealizatsiyaSettlement",
        back_populates="factory",
        cascade="all, delete-orphan",
        foreign_keys="RealizatsiyaSettlement.factory_id",
    )
    users = db.relationship(
        "User",
        back_populates="factory",
        cascade="all, delete-orphan",
    )
    shop_links = db.relationship(
        "ShopFactoryLink",
        back_populates="factory",
        cascade="all, delete-orphan",
    )
    fabrics = db.relationship(
        "Fabric",
        back_populates="factory",
        cascade="all, delete-orphan",
    )
    products = db.relationship(
        "Product",
        back_populates="factory",
        cascade="all, delete-orphan",
    )
    cash_records = db.relationship(
        "CashRecord",
        back_populates="factory",
        cascade="all, delete-orphan",
    )
    shop_orders = db.relationship(
        "ShopOrder",
        back_populates="factory",
        cascade="all, delete-orphan",
    )
    stock_movements = db.relationship(
        "StockMovement",
        back_populates="factory",
        cascade="all, delete-orphan",
    )
    movements = db.relationship(
        "Movement",
        back_populates="factory",
        cascade="all, delete-orphan",
    )
    wholesale_sales = db.relationship(
        "WholesaleSale",
        back_populates="factory",
        cascade="all, delete-orphan",
    )
    shops = db.relationship(
        "Shop",
        foreign_keys="Shop.factory_id",
        overlaps="factory",
        lazy=True,
    )

    def __repr__(self) -> str:
        return f"<Factory id={self.id} name={self.name!r}>"


class Shop(db.Model):
    __tablename__ = "shops"

    id = db.Column(db.Integer, primary_key=True)

    # Legacy compatibility column.
    # The current DB schema still has shops.factory_id as NOT NULL.
    # Real factory membership should be handled through ShopFactoryLink.
    factory_id = db.Column(
        db.Integer,
        db.ForeignKey("factories.id"),
        nullable=False,
        index=True,
    )

    name = db.Column(db.String(128), nullable=False)
    location = db.Column(db.String(128), nullable=True)
    note = db.Column(db.String(255), nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Optional legacy direct relationship
    realizatsiya_settlements = db.relationship(
        "RealizatsiyaSettlement",
        back_populates="shop",
        cascade="all, delete-orphan",
    )
    factory = db.relationship("Factory", foreign_keys=[factory_id], overlaps="shops")

    users = db.relationship("User", back_populates="shop")
    stock_rows = db.relationship("ShopStock", back_populates="shop")
    wholesale_sales = db.relationship(
        "WholesaleSale",
        back_populates="shop",
        cascade="all, delete-orphan",
    )
    sales = db.relationship(
        "Sale",
        back_populates="shop",
        cascade="all, delete-orphan",
    )
    factory_links = db.relationship(
        "ShopFactoryLink",
        back_populates="shop",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Shop id={self.id} name={self.name!r}>"


class ShopFactoryLink(db.Model):
    __tablename__ = "shop_factory_links"

    id = db.Column(db.Integer, primary_key=True)

    shop_id = db.Column(
        db.Integer,
        db.ForeignKey("shops.id"),
        nullable=False,
        index=True,
    )

    factory_id = db.Column(
        db.Integer,
        db.ForeignKey("factories.id"),
        nullable=False,
        index=True,
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    shop = db.relationship("Shop", back_populates="factory_links")
    factory = db.relationship("Factory", back_populates="shop_links")

    __table_args__ = (
        db.UniqueConstraint("shop_id", "factory_id", name="uq_shop_factory_link"),
    )

    def __repr__(self) -> str:
        return f"<ShopFactoryLink shop_id={self.shop_id} factory_id={self.factory_id}>"


# ==========================
#   👤 USERS
# ==========================


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # admin/manager/accountant usually belong to one factory
    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=True)
    factory = db.relationship("Factory", back_populates="users")

    # shop users belong to one shop
    shop_id = db.Column(db.Integer, db.ForeignKey("shops.id"), nullable=True, index=True)
    shop = db.relationship("Shop", back_populates="users")

    # roles: admin, manager, viewer, shop, accountant
    role = db.Column(db.String(32), default="manager", nullable=False)

    # telegram linking relations
    realizatsiya_settlements_created = db.relationship(
        "RealizatsiyaSettlement",
        back_populates="created_by",
        foreign_keys="RealizatsiyaSettlement.created_by_id",
    )
    telegram_links = db.relationship(
        "TelegramLink",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    telegram_link_codes = db.relationship(
        "TelegramLinkCode",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sales_created = db.relationship(
        "Sale",
        back_populates="created_by",
        foreign_keys="Sale.created_by_id",
    )
    wholesale_sales_created = db.relationship(
        "WholesaleSale",
        back_populates="created_by",
        foreign_keys="WholesaleSale.created_by_id",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_manager(self) -> bool:
        return self.role in ("admin", "manager")

    @property
    def is_viewer(self) -> bool:
        return self.role == "viewer"

    @property
    def is_shop(self) -> bool:
        return self.role == "shop"

    @property
    def is_accountant(self) -> bool:
        return self.role == "accountant"

    @property
    def is_superadmin(self) -> bool:
        return self.role == "admin" and self.factory_id is None

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} role={self.role!r}>"


# ==========================
#   🧵 FABRICS & CUTS
# ==========================


def generate_fabric_code() -> str:
    return "FAB-" + uuid.uuid4().hex[:8].upper()


class Fabric(db.Model):
    __tablename__ = "fabrics"

    id = db.Column(db.Integer, primary_key=True)

    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
    factory = db.relationship("Factory", back_populates="fabrics")

    consumptions = db.relationship(
        "FabricConsumption",
        back_populates="fabric",
        cascade="all, delete-orphan",
    )

    public_id = db.Column(
        db.String(32),
        unique=True,
        nullable=False,
        default=generate_fabric_code,
    )

    name = db.Column(db.String(128), nullable=False)
    color = db.Column(db.String(64))
    unit = db.Column(db.String(16), nullable=False, default="kg")
    quantity = db.Column(db.Float, nullable=False, default=0.0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    price_currency = db.Column(db.String(3), default="UZS")
    price_per_unit = db.Column(db.Float)
    category = db.Column(db.String(64))

    cuts = db.relationship(
        "Cut",
        back_populates="fabric",
        cascade="all, delete-orphan",
    )

    def total_value(self) -> float:
        if not self.price_per_unit:
            return 0.0
        return (self.quantity or 0.0) * float(self.price_per_unit)

    def __repr__(self) -> str:
        return f"<Fabric id={self.id} public_id={self.public_id!r} name={self.name!r}>"


class Cut(db.Model):
    __tablename__ = "cuts"

    id = db.Column(db.Integer, primary_key=True)

    fabric_id = db.Column(db.Integer, db.ForeignKey("fabrics.id"), nullable=False)
    used_amount = db.Column(db.Float, nullable=False)
    cut_date = db.Column(db.Date, default=date.today, nullable=False)

    fabric = db.relationship("Fabric", back_populates="cuts")

    def __repr__(self) -> str:
        return f"<Cut id={self.id} fabric_id={self.fabric_id} used_amount={self.used_amount}>"


# ==========================
#   👕 PRODUCTS / PRODUCTION
# ==========================


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)

    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
    factory = db.relationship("Factory", back_populates="products")

    name = db.Column(db.String(128), nullable=False)
    category = db.Column(db.String(64))

    cost_price_per_item = db.Column(db.Float, nullable=False, default=0.0)
    sell_price_per_item = db.Column(db.Float, nullable=False, default=0.0)
    website_image = db.Column(db.String(255))
    fabric_used = db.Column(db.String(255))
    notes = db.Column(db.Text)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    currency = db.Column(db.String(3), default="UZS")
    image_path = db.Column(db.String(255), nullable=True)

    is_published = db.Column(db.Boolean, default=False)
    public_description = db.Column(db.Text)

    sales = db.relationship(
        "Sale",
        back_populates="product",
        cascade="all, delete-orphan",
    )
    productions = db.relationship(
        "Production",
        back_populates="product",
        cascade="all, delete-orphan",
    )
    shop_stock = db.relationship(
        "ShopStock",
        back_populates="product",
        cascade="all, delete-orphan",
    )
    wholesale_sale_items = db.relationship(
        "WholesaleSaleItem",
        back_populates="product",
        cascade="all, delete-orphan",
    )

    def stock_value_cost(self) -> float:
        return self.quantity * (self.cost_price_per_item or 0.0)

    def stock_value_sell(self) -> float:
        return self.quantity * (self.sell_price_per_item or 0.0)

    def stock_profit(self) -> float:
        margin = (self.sell_price_per_item or 0.0) - (self.cost_price_per_item or 0.0)
        return self.quantity * margin

    def __repr__(self) -> str:
        return f"<Product id={self.id} name={self.name!r} factory_id={self.factory_id}>"


class Sale(db.Model):
    __tablename__ = "sales"

    id = db.Column(db.Integer, primary_key=True)

    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    shop_id = db.Column(db.Integer, db.ForeignKey("shops.id"), nullable=True, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    date = db.Column(db.Date, default=date.today, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer_name = db.Column(db.String(128))
    customer_phone = db.Column(db.String(64))

    quantity = db.Column(db.Integer, nullable=False)

    sell_price_per_item = db.Column(db.Float, nullable=False)
    cost_price_per_item = db.Column(db.Float, nullable=False)

    currency = db.Column(db.String(3), default="UZS")

    product = db.relationship("Product", back_populates="sales")
    shop = db.relationship("Shop", back_populates="sales")
    created_by = db.relationship("User", back_populates="sales_created", foreign_keys=[created_by_id])

    @property
    def total_sell(self) -> float:
        return self.quantity * self.sell_price_per_item

    @property
    def total_cost(self) -> float:
        return self.quantity * self.cost_price_per_item

    @property
    def profit(self) -> float:
        return self.total_sell - self.total_cost

    def __repr__(self) -> str:
        return (
            f"<Sale id={self.id} product_id={self.product_id} "
            f"shop_id={self.shop_id} quantity={self.quantity}>"
        )

class WholesaleSale(db.Model):
    __tablename__ = "wholesale_sales"

    id = db.Column(db.Integer, primary_key=True)

    # For mixed-factory wholesale carts this is optional.
    # If all lines belong to one factory, it may be filled.
    factory_id = db.Column(
        db.Integer,
        db.ForeignKey("factories.id"),
        nullable=True,
        index=True,
    )

    shop_id = db.Column(
        db.Integer,
        db.ForeignKey("shops.id"),
        nullable=False,
        index=True,
    )

    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sale_date = db.Column(db.Date, default=date.today, nullable=False)

    customer_name = db.Column(db.String(128), nullable=True)
    customer_phone = db.Column(db.String(64), nullable=True)
    note = db.Column(db.String(255), nullable=True)

    total_skus = db.Column(db.Integer, nullable=False, default=0)
    total_qty = db.Column(db.Integer, nullable=False, default=0)

    subtotal_amount = db.Column(db.Float, nullable=False, default=0.0)
    discount_amount = db.Column(db.Float, nullable=False, default=0.0)
    total_amount = db.Column(db.Float, nullable=False, default=0.0)

    currency = db.Column(db.String(3), nullable=False, default="UZS")

    payment_status = db.Column(db.String(32), nullable=False, default="paid")
    payment_method = db.Column(db.String(32), nullable=True)

    factory = db.relationship("Factory", back_populates="wholesale_sales")
    shop = db.relationship("Shop", back_populates="wholesale_sales")
    created_by = db.relationship(
        "User",
        back_populates="wholesale_sales_created",
        foreign_keys=[created_by_id],
    )

    items = db.relationship(
        "WholesaleSaleItem",
        back_populates="wholesale_sale",
        cascade="all, delete-orphan",
        order_by="WholesaleSaleItem.id.asc()",
    )

    def recalc_totals(self) -> None:
        self.total_skus = len(self.items or [])
        self.total_qty = sum((item.quantity or 0) for item in (self.items or []))
        self.subtotal_amount = sum((item.line_total or 0.0) for item in (self.items or []))
        self.total_amount = max((self.subtotal_amount or 0.0) - (self.discount_amount or 0.0), 0.0)

        source_factory_ids = sorted({
            item.source_factory_id
            for item in (self.items or [])
            if item.source_factory_id
        })
        self.factory_id = source_factory_ids[0] if len(source_factory_ids) == 1 else None

    def __repr__(self) -> str:
        return (
            f"<WholesaleSale id={self.id} factory_id={self.factory_id} "
            f"shop_id={self.shop_id} total_qty={self.total_qty} total_amount={self.total_amount}>"
        )


class WholesaleSaleItem(db.Model):
    __tablename__ = "wholesale_sale_items"

    id = db.Column(db.Integer, primary_key=True)

    wholesale_sale_id = db.Column(
        db.Integer,
        db.ForeignKey("wholesale_sales.id"),
        nullable=False,
        index=True,
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id"),
        nullable=False,
        index=True,
    )

    shop_stock_id = db.Column(
        db.Integer,
        db.ForeignKey("shop_stock.id"),
        nullable=False,
        index=True,
    )

    source_factory_id = db.Column(
        db.Integer,
        db.ForeignKey("factories.id"),
        nullable=False,
        index=True,
    )

    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0.0)
    cost_price_per_item = db.Column(db.Float, nullable=False, default=0.0)
    line_total = db.Column(db.Float, nullable=False, default=0.0)

    product_name_snapshot = db.Column(db.String(128), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="UZS")

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    wholesale_sale = db.relationship("WholesaleSale", back_populates="items")
    product = db.relationship("Product", back_populates="wholesale_sale_items")
    shop_stock = db.relationship("ShopStock", back_populates="wholesale_sale_items")
    source_factory = db.relationship("Factory")

    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_wholesale_sale_items_quantity_positive"),
    )

    def __repr__(self) -> str:
        return (
            f"<WholesaleSaleItem id={self.id} wholesale_sale_id={self.wholesale_sale_id} "
            f"product_id={self.product_id} quantity={self.quantity}>"
        )


class Production(db.Model):
    __tablename__ = "productions"

    id = db.Column(db.Integer, primary_key=True)

    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    date = db.Column(db.Date, default=date.today, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    note = db.Column(db.String(255))

    product = db.relationship("Product", back_populates="productions")
    consumptions = db.relationship(
        "FabricConsumption",
        back_populates="production",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Production id={self.id} product_id={self.product_id} quantity={self.quantity}>"


class ShopStock(db.Model):
    __tablename__ = "shop_stock"

    id = db.Column(db.Integer, primary_key=True)

    shop_id = db.Column(
        db.Integer,
        db.ForeignKey("shops.id"),
        nullable=False,
        index=True,
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id"),
        nullable=False,
        index=True,
    )

    source_factory_id = db.Column(
        db.Integer,
        db.ForeignKey("factories.id"),
        nullable=False,
        index=True,
    )

    quantity = db.Column(db.Integer, nullable=False, default=0)

    shop = db.relationship("Shop", back_populates="stock_rows")
    product = db.relationship("Product", back_populates="shop_stock")
    source_factory = db.relationship("Factory")
    wholesale_sale_items = db.relationship(
        "WholesaleSaleItem",
        back_populates="shop_stock",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.UniqueConstraint(
            "shop_id",
            "product_id",
            "source_factory_id",
            name="uq_shop_stock_shop_product_factory",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ShopStock id={self.id} shop_id={self.shop_id} "
            f"product_id={self.product_id} source_factory_id={self.source_factory_id} "
            f"quantity={self.quantity}>"
        )


# ==========================
#   💸 CASH
# ==========================


class CashRecord(db.Model):
    __tablename__ = "cash_records"

    id = db.Column(db.Integer, primary_key=True)

    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
    factory = db.relationship("Factory", back_populates="cash_records")

    date = db.Column(db.Date, default=date.today, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default="UZS")
    note = db.Column(db.String(255))

    def __repr__(self) -> str:
        return f"<CashRecord id={self.id} factory_id={self.factory_id} amount={self.amount} {self.currency}>"


# ==========================
#   📦 SHOP ORDERS
# ==========================


class ShopOrder(db.Model):
    __tablename__ = "shop_orders"

    id = db.Column(db.Integer, primary_key=True)

    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
    factory = db.relationship("Factory", back_populates="shop_orders")

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer_name = db.Column(db.String(128))
    customer_phone = db.Column(db.String(64))
    note = db.Column(db.String(255))

    status = db.Column(db.String(16), default="pending", nullable=False)

    ready_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_by = db.relationship("User")

    items = db.relationship(
        "ShopOrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
    )

    def recalc_status(self) -> None:
        if self.status in ("completed", "cancelled"):
            return

        if not self.items:
            self.status = "pending"
            return

        if all(item.qty_remaining <= 0 for item in self.items):
            self.status = "ready"
        else:
            self.status = "pending"

    def __repr__(self) -> str:
        return f"<ShopOrder id={self.id} status={self.status!r} factory_id={self.factory_id}>"


class ShopOrderItem(db.Model):
    __tablename__ = "shop_order_items"

    id = db.Column(db.Integer, primary_key=True)

    order_id = db.Column(db.Integer, db.ForeignKey("shop_orders.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)

    qty_requested = db.Column(db.Integer, nullable=False)
    qty_from_shop_now = db.Column(db.Integer, default=0)
    qty_remaining = db.Column(db.Integer, nullable=False)

    order = db.relationship("ShopOrder", back_populates="items")
    product = db.relationship("Product")

    def __repr__(self) -> str:
        return (
            f"<ShopOrderItem id={self.id} order_id={self.order_id} "
            f"product_id={self.product_id} qty_requested={self.qty_requested}>"
        )


# ==========================
#   📜 STOCK MOVEMENTS
# ==========================


class StockMovement(db.Model):
    __tablename__ = "stock_movement"

    id = db.Column(db.Integer, primary_key=True)

    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
    factory = db.relationship("Factory", back_populates="stock_movements")

    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    product = db.relationship("Product", backref="stock_movements")

    qty_change = db.Column(db.Integer, nullable=False)

    source = db.Column(db.String(50))
    destination = db.Column(db.String(50))

    movement_type = db.Column(db.String(50))

    order_id = db.Column(db.Integer, db.ForeignKey("shop_orders.id"))
    order = db.relationship("ShopOrder", backref="stock_movements")

    comment = db.Column(db.String(255))

    def __repr__(self) -> str:
        return (
            f"<StockMovement id={self.id} product_id={self.product_id} "
            f"qty_change={self.qty_change} type={self.movement_type!r}>"
        )


class Movement(db.Model):
    __tablename__ = "movements"

    id = db.Column(db.Integer, primary_key=True)

    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
    factory = db.relationship("Factory", back_populates="movements")

    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    source = db.Column(db.String(64), nullable=False)
    destination = db.Column(db.String(64), nullable=False)
    change = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(255))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship("Product")
    user = db.relationship("User")

    def __repr__(self) -> str:
        return (
            f"<Movement id={self.id} factory_id={self.factory_id} "
            f"product_id={self.product_id} change={self.change}>"
        )


# ==========================
#   ✅ EXCEL IMPORT HISTORY
# ==========================


class ExcelImportBatch(db.Model):
    __tablename__ = "excel_import_batches"

    id = db.Column(db.Integer, primary_key=True)

    factory_id = db.Column(db.Integer, nullable=False, index=True)

    filename = db.Column(db.String(255), nullable=False)
    file_hash = db.Column(db.String(64), nullable=False, index=True)

    file_bytes = db.Column(db.LargeBinary, nullable=True)
    file_size = db.Column(db.Integer, nullable=False, default=0)
    stored_path = db.Column(db.String(512), nullable=True)

    uploaded_by_id = db.Column(db.Integer, nullable=True)

    status = db.Column(db.String(32), nullable=False, default="uploaded")
    error = db.Column(db.Text, nullable=True)

    sheets_selected = db.Column(db.Text, nullable=True)
    stats_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    imported_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            "factory_id", "file_hash", name="uq_excel_batch_factory_hash"
        ),
    )


class ExcelImportRow(db.Model):
    __tablename__ = "excel_import_rows"

    id = db.Column(db.Integer, primary_key=True)
    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)

    kind = db.Column(db.String(32), nullable=False)
    row_hash = db.Column(db.String(64), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "factory_id", "kind", "row_hash", name="uq_excel_import_row"
        ),
    )

    def __repr__(self) -> str:
        return f"<ExcelImportRow id={self.id} factory_id={self.factory_id} kind={self.kind!r}>"


# ==========================
#   🛒 PUBLIC CUSTOMER ORDERS
# ==========================


class CustomerOrder(db.Model):
    __tablename__ = "customer_orders"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    customer_name = db.Column(db.String(128), nullable=False)
    customer_phone = db.Column(db.String(64), nullable=False)
    customer_city = db.Column(db.String(64), nullable=True)

    note = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(16), default="new", nullable=False)

    items = db.relationship(
        "CustomerOrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<CustomerOrder id={self.id} status={self.status!r}>"


class CustomerOrderItem(db.Model):
    __tablename__ = "customer_order_items"

    id = db.Column(db.Integer, primary_key=True)

    order_id = db.Column(
        db.Integer, db.ForeignKey("customer_orders.id"), nullable=False
    )
    order = db.relationship("CustomerOrder", back_populates="items")

    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    product = db.relationship("Product")

    qty = db.Column(db.Integer, nullable=False, default=1)

    product_name = db.Column(db.String(128), nullable=False)
    price = db.Column(db.Float, nullable=False, default=0.0)
    currency = db.Column(db.String(3), default="UZS")

    def __repr__(self) -> str:
        return (
            f"<CustomerOrderItem id={self.id} order_id={self.order_id} "
            f"product_id={self.product_id} qty={self.qty}>"
        )


# ==========================
#   🧵 FABRIC CONSUMPTION
# ==========================


class FabricConsumption(db.Model):
    __tablename__ = "fabric_consumptions"

    id = db.Column(db.Integer, primary_key=True)

    factory_id = db.Column(
        db.Integer, db.ForeignKey("factories.id"), nullable=False, index=True
    )

    fabric_id = db.Column(
        db.Integer, db.ForeignKey("fabrics.id"), nullable=False, index=True
    )
    production_id = db.Column(
        db.Integer, db.ForeignKey("productions.id"), nullable=False, index=True
    )

    used_amount = db.Column(db.Float, nullable=False, default=0.0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    fabric = db.relationship("Fabric", back_populates="consumptions")
    production = db.relationship("Production", back_populates="consumptions")

    def __repr__(self) -> str:
        return (
            f"<FabricConsumption id={self.id} factory_id={self.factory_id} "
            f"fabric_id={self.fabric_id} production_id={self.production_id} "
            f"used_amount={self.used_amount}>"
        )


# ==========================
#   🤖 TELEGRAM LINKING
# ==========================


class TelegramLink(db.Model):
    __tablename__ = "telegram_links"

    id = db.Column(db.Integer, primary_key=True)

    telegram_chat_id = db.Column(
        db.BigInteger,
        unique=True,
        nullable=False,
        index=True,
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    user = db.relationship("User", back_populates="telegram_links")

    factory_id = db.Column(db.Integer, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<TelegramLink id={self.id} telegram_chat_id={self.telegram_chat_id} "
            f"user_id={self.user_id} factory_id={self.factory_id}>"
        )


class TelegramLinkCode(db.Model):
    __tablename__ = "telegram_link_codes"

    id = db.Column(db.Integer, primary_key=True)

    code = db.Column(
        db.String(32),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: secrets.token_urlsafe(8),
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    user = db.relationship("User", back_populates="telegram_link_codes")

    factory_id = db.Column(db.Integer, nullable=False, index=True)

    expires_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.utcnow() + timedelta(minutes=10),
    )
    used_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @staticmethod
    def generate(user_id: int, factory_id: int, minutes: int = 10) -> "TelegramLinkCode":
        code = secrets.token_hex(3).upper()
        return TelegramLinkCode(
            code=code,
            user_id=user_id,
            factory_id=factory_id,
            expires_at=datetime.utcnow() + timedelta(minutes=minutes),
        )

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    def is_used(self) -> bool:
        return self.used_at is not None

    def __repr__(self) -> str:
        return (
            f"<TelegramLinkCode id={self.id} code={self.code!r} "
            f"user_id={self.user_id} factory_id={self.factory_id}>"
        )
class RealizatsiyaSettlement(db.Model):
    __tablename__ = "realizatsiya_settlements"

    id = db.Column(db.Integer, primary_key=True)

    shop_id = db.Column(
        db.Integer,
        db.ForeignKey("shops.id"),
        nullable=False,
        index=True,
    )

    factory_id = db.Column(
        db.Integer,
        db.ForeignKey("factories.id"),
        nullable=False,
        index=True,
    )

    settlement_date = db.Column(db.Date, default=date.today, nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    currency = db.Column(db.String(3), nullable=False, default="UZS")
    note = db.Column(db.String(255), nullable=True)

    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    shop = db.relationship("Shop", back_populates="realizatsiya_settlements")
    factory = db.relationship(
        "Factory",
        back_populates="realizatsiya_settlements_received",
        foreign_keys=[factory_id],
    )
    created_by = db.relationship(
        "User",
        back_populates="realizatsiya_settlements_created",
        foreign_keys=[created_by_id],
    )

    __table_args__ = (
        db.CheckConstraint("amount > 0", name="ck_realizatsiya_settlements_amount_positive"),
    )

    def __repr__(self) -> str:
        return (
            f"<RealizatsiyaSettlement id={self.id} shop_id={self.shop_id} "
            f"factory_id={self.factory_id} amount={self.amount}>"
        )
