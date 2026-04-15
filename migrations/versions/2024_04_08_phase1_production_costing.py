"""phase 1 production costing

Revision ID: 20260408_phase1
Revises: fae5e9edf9a0
Create Date: 2026-04-08 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260408_phase1"
down_revision = "fae5e9edf9a0"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}

def upgrade():
    if not _has_column("stock_movement", "unit_price"):
        op.add_column("stock_movement", sa.Column("unit_price", sa.Float(), nullable=True))
    if not _has_column("stock_movement", "total_value"):
        op.add_column("stock_movement", sa.Column("total_value", sa.Float(), nullable=True))
    if not _has_column("stock_movement", "currency"):
        op.add_column("stock_movement", sa.Column("currency", sa.String(length=3), nullable=True))
    if not _has_column("stock_movement", "locked_unit_price"):
        op.add_column("stock_movement", sa.Column("locked_unit_price", sa.Float(), nullable=True))
    if not _has_column("stock_movement", "locked_total_value"):
        op.add_column("stock_movement", sa.Column("locked_total_value", sa.Float(), nullable=True))

    if not _has_column("products", "factory_transfer_price"):
        op.add_column("products", sa.Column("factory_transfer_price", sa.Float(), nullable=True))

    if not _has_column("productions", "qty_issued_to_workers"):
        op.add_column("productions", sa.Column("qty_issued_to_workers", sa.Integer(), nullable=True))
    if not _has_column("productions", "qty_finished_good"):
        op.add_column("productions", sa.Column("qty_finished_good", sa.Integer(), nullable=True))
    if not _has_column("productions", "qty_defective"):
        op.add_column("productions", sa.Column("qty_defective", sa.Integer(), nullable=True))
    if not _has_column("productions", "qty_unfinished"):
        op.add_column("productions", sa.Column("qty_unfinished", sa.Integer(), nullable=True))
    if not _has_column("productions", "qty_payable"):
        op.add_column("productions", sa.Column("qty_payable", sa.Integer(), nullable=True))
    if not _has_column("productions", "shortfall_reason"):
        op.add_column("productions", sa.Column("shortfall_reason", sa.String(length=255), nullable=True))

def downgrade():
    if _has_column("stock_movement", "unit_price"):
        op.drop_column("stock_movement", "unit_price")
    if _has_column("stock_movement", "total_value"):
        op.drop_column("stock_movement", "total_value")
    if _has_column("stock_movement", "currency"):
        op.drop_column("stock_movement", "currency")
    if _has_column("stock_movement", "locked_unit_price"):
        op.drop_column("stock_movement", "locked_unit_price")
    if _has_column("stock_movement", "locked_total_value"):
        op.drop_column("stock_movement", "locked_total_value")
    if _has_column("products", "factory_transfer_price"):
        op.drop_column("products", "factory_transfer_price")
    if _has_column("productions", "qty_issued_to_workers"):
        op.drop_column("productions", "qty_issued_to_workers")
    if _has_column("productions", "qty_finished_good"):
        op.drop_column("productions", "qty_finished_good")
    if _has_column("productions", "qty_defective"):
        op.drop_column("productions", "qty_defective")
    if _has_column("productions", "qty_unfinished"):
        op.drop_column("productions", "qty_unfinished")
    if _has_column("productions", "qty_payable"):
        op.drop_column("productions", "qty_payable")
    if _has_column("productions", "shortfall_reason"):
        op.drop_column("productions", "shortfall_reason")
