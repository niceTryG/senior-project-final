"""add cutting orders

Revision ID: 20260408_cutting_order
Revises: 20260408_phase1
Create Date: 2026-04-08 00:10:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260408_cutting_order"
down_revision = "20260408_phase1"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table_name)

def upgrade():
    if not _has_table("cutting_orders"):
        op.create_table(
            "cutting_orders",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("factory_id", sa.Integer(), sa.ForeignKey("factories.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("cut_date", sa.Date(), nullable=False),
            sa.Column("sets_cut", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_cutting_orders_factory_id", "cutting_orders", ["factory_id"])
        op.create_index("ix_cutting_orders_product_id", "cutting_orders", ["product_id"])

    if not _has_table("cutting_order_materials"):
        op.create_table(
            "cutting_order_materials",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("cutting_order_id", sa.Integer(), sa.ForeignKey("cutting_orders.id"), nullable=False),
            sa.Column("material_id", sa.Integer(), sa.ForeignKey("fabrics.id"), nullable=False),
            sa.Column("used_amount", sa.Float(), nullable=False),
            sa.Column("unit_cost_snapshot", sa.Float(), nullable=False),
            sa.Column("total_cost_snapshot", sa.Float(), nullable=False),
        )
        op.create_index("ix_cutting_order_materials_cutting_order_id", "cutting_order_materials", ["cutting_order_id"])
        op.create_index("ix_cutting_order_materials_material_id", "cutting_order_materials", ["material_id"])

def downgrade():
    if _has_table("cutting_order_materials"):
        op.drop_index("ix_cutting_order_materials_material_id", table_name="cutting_order_materials")
        op.drop_index("ix_cutting_order_materials_cutting_order_id", table_name="cutting_order_materials")
        op.drop_table("cutting_order_materials")
    if _has_table("cutting_orders"):
        op.drop_index("ix_cutting_orders_product_id", table_name="cutting_orders")
        op.drop_index("ix_cutting_orders_factory_id", table_name="cutting_orders")
        op.drop_table("cutting_orders")
