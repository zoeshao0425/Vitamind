"""Added translation column

Revision ID: 7cdbf6d3499f
Revises: 
Create Date: 2023-07-01 16:34:13.564479

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7cdbf6d3499f'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('word_list', sa.Column('translation', sa.String(length=120), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('word_list', 'translation')
    # ### end Alembic commands ###