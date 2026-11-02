"""Add server/node runtime overrides; preserve all existing owner data."""
from alembic import op
revision = "resources_20261020_0003"
down_revision = "resources_20261019_0002"
branch_labels = None
depends_on = None
source_signature = "f4cfcd457b042ff2dc67607e64684cc2fc436a2b4f927350c448916a5eebd49e"

def upgrade() -> None:
    op.execute("CREATE TABLE resources.runtime_policies (scope_key VARCHAR(64) PRIMARY KEY, policy_values JSONB NOT NULL, sequence BIGINT NOT NULL CONSTRAINT ck_runtime_policy_sequence CHECK(sequence > 0))")

def downgrade() -> None:
    op.drop_table("runtime_policies", schema="resources")
