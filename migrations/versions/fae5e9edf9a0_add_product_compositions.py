"""add product compositions

Revision ID: fae5e9edf9a0
Revises: 20260329_0001
Create Date: 2026-04-02 22:06:16.529331

"""
from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = 'fae5e9edf9a0'
down_revision = '20260329_0001'
branch_labels = None
depends_on = None


def upgrade():
    # The baseline migration intentionally manages legacy schema_migrations.
    # Keep this revision as a no-op so existing databases can advance safely.
    pass


def downgrade():
    pass
