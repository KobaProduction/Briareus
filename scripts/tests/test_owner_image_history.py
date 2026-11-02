"""Migration history and exact image shipment acceptance invariants."""

from pathlib import Path

import pytest

from owner_image_history import MigrationHistory, migration_revision, reviewed_chain
from verify_flat_batch import owner_image_migration_errors


def test_static_parser_never_executes_migration_source() -> None:
    revision = migration_revision(
        "0001.py", "revision = 'first'\ndown_revision = None\nraise RuntimeError('do not run')"
    )
    assert revision.revision == "first"
    assert revision.predecessor is None


def test_duplicate_revision_is_rejected_even_with_different_filenames() -> None:
    first = migration_revision("0001.py", "revision = 'same'")
    duplicate = migration_revision("0002.py", "revision = 'same'")
    with pytest.raises(ValueError, match="invalid source Alembic revision"):
        MigrationHistory((first, duplicate))


@pytest.mark.parametrize(
    "source",
    [
        "revision = 7",
        "revision = 'first'\ndown_revision = ['other']",
        "revision = execute_external_code()",
    ],
)
def test_revision_requires_safe_literal_identity_and_predecessor(source: str) -> None:
    with pytest.raises((ValueError, TypeError)):
        migration_revision("0001.py", source)


def test_reviewed_chain_is_owner_scoped_literal_without_imports() -> None:
    source = "_REVIEWED_VERSIONS: dict = {'resources': ('first', 'second')}\nraise RuntimeError()"
    assert reviewed_chain(source, "resources") == ("first", "second")
    with pytest.raises(ValueError, match="invalid reviewed owner graph"):
        reviewed_chain(source, "platform")


def test_history_rejects_changed_ancestors_unreviewed_revisions_and_duplicate_copies() -> None:
    history = MigrationHistory(
        (
            migration_revision("first.py", "revision = 'first'"),
            migration_revision("second.py", "revision = 'second'\ndown_revision = 'foreign'"),
            migration_revision("extra.py", "revision = 'unreviewed'"),
        )
    )
    folder = "services/resources"
    first_copy = (
        f"COPY {folder}/migrations/versions/first.py "
        "/app/src/common/alembic_owners/resources/versions/first.py\n"
    )
    errors = history.image_errors(folder, "resources", ("first", "second"), first_copy * 2, ["**"])
    assert folder + ": shipped migration files differ from reviewed graph" in errors
    assert folder + ": owner history has unexpected ancestor" in errors
    assert folder + ": Dockerfile missing migration first.py" in errors
    assert folder + ": Docker build context excludes migration second.py" in errors


def test_image_adapter_preserves_error_mapping_and_accepts_exact_history(tmp_path: Path) -> None:
    common = tmp_path / "services/common"
    common.mkdir(parents=True)
    (common / "owner_migrations.py").write_text(
        "_REVIEWED_VERSIONS: dict = {'resources': ('first',)}"
    )
    folder = "services/resources"
    owner = tmp_path / folder
    versions = owner / "migrations/versions"
    versions.mkdir(parents=True)
    (versions / "0001.py").write_text("revision = 'first'\ndown_revision = None")
    (owner / "Dockerfile.dockerignore").write_text(
        "**\n!services/resources/migrations/versions/0001.py\n"
    )
    dockerfile = (
        "COPY services/resources/migrations/versions/0001.py "
        "/app/src/common/alembic_owners/resources/versions/0001.py\n"
    )
    assert owner_image_migration_errors(folder, owner, dockerfile, source_root=tmp_path) == []
    (versions / "0001.py").write_text("revision = unsafe()")
    assert owner_image_migration_errors(folder, owner, dockerfile, source_root=tmp_path) == [
        folder + ": owner migration source cannot be parsed safely"
    ]
