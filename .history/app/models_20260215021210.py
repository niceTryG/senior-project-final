# ==== app/models.py (REPLACE FULL FILE) ====
from datetime import datetime, date
import uuid

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
    users = db.relationship(
        "User",
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

    def __repr__(self) -> str:
        return f"<Factory id={self.id} name={self.name!r}>"


# ==========================
#   👤 USERS
# ==========================


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # each user belongs to one factory (tenant)
    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=True)
    factory = db.relationship("Factory", back_populates="users")

    # roles: admin, manager, viewer, shop, accountant
    role = db.Column(db.String(32), default="manager", nullable=False)

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
        """
        Superadmin can see all factories if factory_id is NULL.
        Normal admins/managers have factory_id set.
        """
        return self.role == "admin" and self.factory_id is None

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} role={self.role!r}>"


# ==========================
#   🧵 FABRICS & CUTS
# ==========================


def generate_fabric_code() -> str:
    """Generate a public-facing fabric code, e.g. FAB-8F3A12C9."""
    return "FAB-" + uuid.uuid4().hex[:8].upper()


class Fabric(db.Model):
    __tablename__ = "fabrics"

    id = db.Column(db.Integer, primary_key=True)

    # factory owner of this fabric
    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
    factory = db.relationship("Factory", back_populates="fabrics")

    # public-facing unique code for QR, UI, etc.
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
        """
        Total value of this fabric in its native currency
        (quantity * price_per_unit). If price is None → 0.
        """
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

    # each product belongs to a factory
    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)
    factory = db.relationship("Factory", back_populates="products")

    name = db.Column(db.String(128), nullable=False)
    category = db.Column(db.String(64))

    # prices
    cost_price_per_item = db.Column(db.Float, nullable=False, default=0.0)
    sell_price_per_item = db.Column(db.Float, nullable=False, default=0.0)

    quantity = db.Column(db.Integer, nullable=False, default=0)
    currency = db.Column(db.String(3), default="UZS")
    image_path = db.Column(db.String(255), nullable=True)

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
        uselist=False,
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
    date = db.Column(db.Date, default=date.today, nullable=False)

    customer_name = db.Column(db.String(128))
    customer_phone = db.Column(db.String(64))

    quantity = db.Column(db.Integer, nullable=False)

    # prices at the moment of sale
    sell_price_per_item = db.Column(db.Float, nullable=False)
    cost_price_per_item = db.Column(db.Float, nullable=False)

    currency = db.Column(db.String(3), default="UZS")

    product = db.relationship("Product", back_populates="sales")

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
        return f"<Sale id={self.id} product_id={self.product_id} quantity={self.quantity}>"


class Production(db.Model):
    __tablename__ = "productions"

    id = db.Column(db.Integer, primary_key=True)

    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    date = db.Column(db.Date, default=date.today, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    note = db.Column(db.String(255))

    product = db.relationship("Product", back_populates="productions")

    def __repr__(self) -> str:
        return f"<Production id={self.id} product_id={self.product_id} quantity={self.quantity}>"


class ShopStock(db.Model):
    __tablename__ = "shop_stock"

    id = db.Column(db.Integer, primary_key=True)

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id"),
        unique=True,
        nullable=False,
    )
    quantity = db.Column(db.Integer, nullable=False, default=0)

    product = db.relationship("Product", back_populates="shop_stock")

    @property
    def total_value(self) -> float:
        price = self.product.sell_price_per_item or 0.0
        return self.quantity * price

    def __repr__(self) -> str:
        return f"<ShopStock id={self.id} product_id={self.product_id} quantity={self.quantity}>"


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

    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)

    filename = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(500), nullable=False)  # filesystem path (server)
    file_hash = db.Column(db.String(64), nullable=False)     # sha256 hex of bytes

    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    uploaded_by = db.relationship("User")

    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    imported_at = db.Column(db.DateTime)

    status = db.Column(db.String(32), default="uploaded", nullable=False)  # uploaded/imported/failed

    sheets_selected = db.Column(db.Text)  # JSON list of sheet names
    stats_json = db.Column(db.Text)       # JSON dict: counts, warnings, etc.
    error = db.Column(db.Text)

    __table_args__ = (
        db.UniqueConstraint("factory_id", "file_hash", name="uq_excel_import_batch_filehash"),
    )

    def __repr__(self) -> str:
        return f"<ExcelImportBatch id={self.id} factory_id={self.factory_id} filename={self.filename!r} status={self.status!r}>"


class ExcelImportRow(db.Model):
    """
    Small dedupe table: remembers imported rows by hash.
    Prevents importing the same sale/cash line twice.
    """
    __tablename__ = "excel_import_rows"

    id = db.Column(db.Integer, primary_key=True)
    factory_id = db.Column(db.Integer, db.ForeignKey("factories.id"), nullable=False)

    kind = db.Column(db.String(32), nullable=False)   # "sale" / "cash"
    row_hash = db.Column(db.String(64), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("factory_id", "kind", "row_hash", name="uq_excel_import_row"),
    )

    def __repr__(self) -> str:
        return f"<ExcelImportRow id={self.id} factory_id={self.factory_id} kind={self.kind!r}>"
