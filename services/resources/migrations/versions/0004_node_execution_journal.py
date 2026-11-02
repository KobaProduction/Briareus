"""Add Node execution journal to the existing Resources owner database."""

from alembic import op

revision = "resources_20261021_0004"
down_revision = "resources_20261020_0003"
branch_labels = None
depends_on = None
source_signature = "334fac98bf91a945c34d4cebab017d8c999453f37025a20ffa8a881ed2150d09"


def upgrade() -> None:
    op.execute(
        "CREATE TABLE resources.node_journal_admissions ( node_uuid UUID NOT NULL, "
        "request_uuid UUID NOT NULL, expires_at BIGINT NOT NULL, PRIMARY KEY (node_uuid, "
        "request_uuid), FOREIGN KEY(node_uuid) REFERENCES resources.nodes (id) ON DELETE "
        "RESTRICT ) "
    )
    op.execute(
        "CREATE TABLE resources.node_journal_applied ( node_uuid UUID NOT NULL, "
        "placement_uuid UUID NOT NULL, spec TEXT NOT NULL, container TEXT NOT NULL, PRIMARY "
        "KEY (node_uuid, placement_uuid), FOREIGN KEY(node_uuid) REFERENCES resources.nodes "
        "(id) ON DELETE RESTRICT ) "
    )
    op.execute(
        "CREATE TABLE resources.node_journal_configuration ( node_uuid UUID NOT NULL, "
        "sequence BIGINT NOT NULL, record TEXT NOT NULL, PRIMARY KEY (node_uuid), CONSTRAINT "
        "ck_node_journal_configuration_sequence CHECK (sequence > 0), FOREIGN KEY(node_uuid) "
        "REFERENCES resources.nodes (id) ON DELETE RESTRICT ) "
    )
    op.execute(
        "CREATE TABLE resources.node_journal_events ( node_uuid UUID NOT NULL, cursor BIGINT "
        "NOT NULL, topic VARCHAR(32) NOT NULL, payload TEXT NOT NULL, created_at TIMESTAMP "
        "WITH TIME ZONE NOT NULL, PRIMARY KEY (node_uuid, cursor), FOREIGN KEY(node_uuid) "
        "REFERENCES resources.nodes (id) ON DELETE RESTRICT ) "
    )
    op.execute(
        "CREATE TABLE resources.node_journal_leases ( node_uuid UUID NOT NULL, session_uuid "
        "UUID NOT NULL, epoch BIGINT NOT NULL, expires_at TIMESTAMP WITH TIME ZONE NOT NULL, "
        "cursor BIGINT NOT NULL, PRIMARY KEY (node_uuid), CONSTRAINT "
        "ck_node_journal_lease_counters CHECK (epoch > 0 AND cursor >= 0), FOREIGN "
        "KEY(node_uuid) REFERENCES resources.nodes (id) ON DELETE RESTRICT ) "
    )
    op.execute(
        "CREATE TABLE resources.node_journal_operations ( node_uuid UUID NOT NULL, "
        "operation_uuid UUID NOT NULL, placement_uuid UUID NOT NULL, sequence BIGINT NOT "
        "NULL, desired TEXT NOT NULL, fingerprint VARCHAR(64) NOT NULL, phase VARCHAR(16) NOT "
        "NULL, previous TEXT, container TEXT, error VARCHAR(64), diagnostic TEXT, PRIMARY KEY "
        "(node_uuid, operation_uuid), CONSTRAINT uq_node_journal_sequence UNIQUE (node_uuid, "
        "placement_uuid, sequence), CONSTRAINT ck_node_journal_operation_sequence CHECK "
        "(sequence > 0), CONSTRAINT ck_node_journal_operation_phase CHECK (phase IN "
        "('queued','pulling','stopping','creating','checking','rolling_back',"
        "'succeeded','failed')), "
        "FOREIGN KEY(node_uuid) REFERENCES resources.nodes (id) ON DELETE RESTRICT ) "
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_node_journal_active ON resources.node_journal_operations "
        "(node_uuid, placement_uuid) WHERE phase NOT IN ('succeeded','failed') "
    )
    op.execute(
        "CREATE TABLE resources.node_journal_requests ( node_uuid UUID NOT NULL, request_uuid "
        "UUID NOT NULL, fingerprint VARCHAR(64) NOT NULL, response TEXT NOT NULL, expires_at "
        "BIGINT NOT NULL, PRIMARY KEY (node_uuid, request_uuid), FOREIGN KEY(node_uuid) "
        "REFERENCES resources.nodes (id) ON DELETE RESTRICT ) "
    )
    op.execute(
        "CREATE TABLE resources.node_pair_intents ( operation_uuid UUID NOT NULL, node_uuid "
        "UUID NOT NULL, public_key TEXT NOT NULL, actor_uuid UUID NOT NULL, project_uuid UUID "
        "NOT NULL, fingerprint VARCHAR(64) NOT NULL, expected_sequence BIGINT NOT NULL, "
        "expires_at TIMESTAMP WITH TIME ZONE NOT NULL, PRIMARY KEY (operation_uuid), FOREIGN "
        "KEY(node_uuid) REFERENCES resources.nodes (id) ON DELETE RESTRICT ) "
    )


def downgrade() -> None:
    op.drop_table("node_pair_intents", schema="resources")
    op.drop_table("node_journal_requests", schema="resources")
    op.drop_table("node_journal_operations", schema="resources")
    op.drop_table("node_journal_leases", schema="resources")
    op.drop_table("node_journal_events", schema="resources")
    op.drop_table("node_journal_configuration", schema="resources")
    op.drop_table("node_journal_applied", schema="resources")
    op.drop_table("node_journal_admissions", schema="resources")
