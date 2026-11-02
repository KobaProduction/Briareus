"""Version Resources node JSONB without changing execution wire data or fingerprints.

Apply through the Resources owner's ordinary Alembic release phase. This source
change does not execute migrations or reset any database. The typed reader has
one schema and fails closed on unversioned or unsupported records.
"""

from alembic import op

revision = "resources_20261023_0005"
down_revision = "resources_20261021_0004"
branch_labels = None
depends_on = None
source_signature = "334fac98bf91a945c34d4cebab017d8c999453f37025a20ffa8a881ed2150d09"


_UPGRADE = (
    ("UPDATE resources.node_operations SET previous = NULL WHERE previous = 'null'::jsonb"),
    (
        "UPDATE resources.nodes SET budget = jsonb_build_object('schema_version', 1, 'record', "
        "budget) WHERE budget IS NOT NULL AND NOT (budget ? 'schema_version')"
    ),
    (
        "UPDATE resources.module_artifacts SET inputs = jsonb_build_object('schema_version', "
        "1, 'record', inputs) WHERE inputs IS NOT NULL AND NOT (inputs ? 'schema_version')"
    ),
    (
        "UPDATE resources.module_artifacts SET configuration_contract = "
        "jsonb_build_object('schema_version', 1, 'record', configuration_contract) WHERE "
        "configuration_contract IS NOT NULL AND NOT (configuration_contract ? "
        "'schema_version')"
    ),
    (
        "UPDATE resources.module_artifacts SET storage_contract = "
        "jsonb_build_object('schema_version', 1, 'record', storage_contract) WHERE "
        "storage_contract IS NOT NULL AND NOT (storage_contract ? 'schema_version')"
    ),
    (
        "UPDATE resources.node_modules SET configuration = "
        "jsonb_build_object('schema_version', 1, 'record', configuration) WHERE configuration "
        "IS NOT NULL AND NOT (configuration ? 'schema_version')"
    ),
    (
        "UPDATE resources.node_modules SET limits = jsonb_build_object('schema_version', 1, "
        "'record', limits) WHERE limits IS NOT NULL AND NOT (limits ? 'schema_version')"
    ),
    (
        "UPDATE resources.node_operations SET desired = jsonb_build_object('schema_version', "
        "1, 'record', desired) WHERE desired IS NOT NULL AND NOT (desired ? 'schema_version')"
    ),
    (
        "UPDATE resources.node_operations SET previous = jsonb_build_object('schema_version', "
        "1, 'record', previous) WHERE previous IS NOT NULL AND NOT (previous ? "
        "'schema_version')"
    ),
    (
        "UPDATE resources.runtime_policies SET policy_values = "
        "jsonb_build_object('schema_version', 1, 'record', policy_values) WHERE policy_values "
        "IS NOT NULL AND NOT (policy_values ? 'schema_version')"
    ),
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Typed Resources records require an explicit coordinated owner rollback")
