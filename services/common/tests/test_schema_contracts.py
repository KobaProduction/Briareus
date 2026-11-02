"""Readiness rejects changed security contracts without invoking migrations."""

import unittest
from collections.abc import Iterable
from dataclasses import dataclass, replace

from common.application.schema_verification import SchemaComparison, VerifyOwnerSchema
from common.domain.schema_contracts import (
    ColumnShape,
    ForeignKeyShape,
    IndexShape,
    OwnerSchemaRejected,
    TableSchema,
    UniqueShape,
    require_sensitive_default,
)


def table() -> TableSchema:
    return TableSchema(
        "owner.items",
        frozenset({"uuid"}),
        (ColumnShape("uuid", False, "UUID"),),
        ("uuid",),
        frozenset({"ck_items"}),
        (UniqueShape(("uuid",), "uq_items"),),
        (IndexShape("ix_items", ("uuid",), False, "uuid IS NOT NULL"),),
        frozenset(),
    )


@dataclass
class InspectionFixture:
    version: str | None
    pairs: tuple[SchemaComparison, ...]
    inspected: bool = False

    def revision(self) -> str | None:
        return self.version

    def comparisons(self) -> Iterable[SchemaComparison]:
        self.inspected = True
        return self.pairs

    def table_count(self) -> int:
        return len(self.pairs)


class SchemaContractTests(unittest.TestCase):
    def test_revision_mismatch_denies_before_reflecting_tables(self) -> None:
        source = InspectionFixture("old", ())
        with self.assertRaisesRegex(OwnerSchemaRejected, "revision mismatch"):
            VerifyOwnerSchema(source, "reviewed").execute()
        self.assertFalse(source.inspected)

    def test_readonly_verification_returns_reviewed_revision_and_count(self) -> None:
        reviewed = table()
        source = InspectionFixture("reviewed", (SchemaComparison(reviewed, reviewed),))
        result = VerifyOwnerSchema(source, "reviewed").execute()
        self.assertEqual((result.revision, result.tables), ("reviewed", 1))

    def test_column_primary_key_check_and_foreign_key_changes_deny(self) -> None:
        reviewed = table()
        variations = (
            replace(reviewed, column_names=frozenset()),
            replace(reviewed, columns=(ColumnShape("uuid", True, "UUID"),)),
            replace(reviewed, columns=(ColumnShape("uuid", False, "TEXT"),)),
            replace(reviewed, primary_key=()),
            replace(reviewed, checks=frozenset()),
            replace(
                reviewed,
                foreign_keys=frozenset({ForeignKeyShape(("uuid",), "other", "items", ("uuid",))}),
            ),
        )
        for observed in variations:
            with self.subTest(observed=observed), self.assertRaises(OwnerSchemaRejected):
                reviewed.require_matches(observed)

    def test_duplicate_extra_missing_and_renamed_unique_contracts_deny(self) -> None:
        reviewed = table()
        variations = (
            (),
            (UniqueShape(("uuid",), "wrong"),),
            reviewed.uniques * 2,
            (*reviewed.uniques, UniqueShape(("other",), "extra")),
        )
        for uniques in variations:
            with (
                self.subTest(uniques=uniques),
                self.assertRaisesRegex(OwnerSchemaRejected, "UNIQUE"),
            ):
                reviewed.require_matches(replace(reviewed, uniques=uniques))

    def test_unnamed_reviewed_unique_accepts_generated_database_name(self) -> None:
        reviewed = replace(table(), uniques=(UniqueShape(("uuid",), None),))
        reviewed.require_matches(replace(reviewed, uniques=(UniqueShape(("uuid",), "generated"),)))

    def test_index_missing_column_uniqueness_and_predicate_changes_deny(self) -> None:
        reviewed = table()
        variations = (
            (),
            (IndexShape("ix_items", ("other",), False, "uuid IS NOT NULL"),),
            (IndexShape("ix_items", ("uuid",), True, "uuid IS NOT NULL"),),
            (IndexShape("ix_items", ("uuid",), False, None),),
            (IndexShape("ix_items", ("uuid",), False, "uuid IS NULL"),),
        )
        for indexes in variations:
            with self.subTest(indexes=indexes), self.assertRaises(OwnerSchemaRejected):
                reviewed.require_matches(replace(reviewed, indexes=indexes))

    def test_postgresql_active_default_representations_are_accepted(self) -> None:
        for value in ("'active'", "'active'::character varying", "('active'::text)"):
            require_sensitive_default(
                "projects.projects", ColumnShape("lifecycle_status", False, "VARCHAR", value)
            )

    def test_inactive_embedded_literal_and_function_defaults_deny(self) -> None:
        for value in (
            "'inactive'",
            "'preactive'::text",
            "'ACTIVE'::text",
            "lower('active')",
            "('in' || 'active')::text",
            "'active::text'",
            "some_active_function()",
        ):
            with self.subTest(value=value), self.assertRaises(OwnerSchemaRejected):
                require_sensitive_default(
                    "projects.projects", ColumnShape("lifecycle_status", False, "VARCHAR", value)
                )

    def test_telemetry_defaults_remain_deny_by_default(self) -> None:
        for value in ("false", "false::boolean", "'false'::boolean"):
            require_sensitive_default(
                "identity.users", ColumnShape("browser_telemetry_opt_in", False, "BOOLEAN", value)
            )
        with self.assertRaises(OwnerSchemaRejected):
            require_sensitive_default(
                "identity.users", ColumnShape("browser_telemetry_opt_in", False, "BOOLEAN", "true")
            )

    def test_current_postgresql_predicate_forms_match_reviewed_membership_and_nulls(self) -> None:
        pairs = (
            (
                "status IN ('dispatched','unknown')",
                "((status)::text = ANY ((ARRAY['dispatched'::character varying, "
                "'unknown'::character varying])::text[]))",
            ),
            (
                "phase NOT IN ('succeeded','failed')",
                "((phase)::text <> ALL (ARRAY['succeeded'::text, 'failed'::text]))",
            ),
            (
                "owner_team_id IS NOT NULL AND deleted_at IS NULL",
                "((owner_team_id IS NOT NULL) AND (deleted_at IS NULL))",
            ),
        )
        for reviewed, observed in pairs:
            with self.subTest(reviewed=reviewed):
                IndexShape("ix", ("uuid",), False, reviewed).require_matches(
                    IndexShape("ix", ("uuid",), False, observed)
                )

    def test_wrong_predicate_constants_operators_columns_and_function_calls_deny(self) -> None:
        reviewed = IndexShape(
            "ix", ("uuid",), False, "status IN ('reserved','dispatched','unknown')"
        )
        variations = (
            "status IN ('reserved','dispatched')",
            "status IN ('reserved::text','dispatched','unknown')",
            "other IN ('reserved','dispatched','unknown')",
            "status <> ALL (ARRAY['reserved','dispatched','unknown'])",
            "status = ALL (ARRAY['reserved','dispatched','unknown'])",
            "status IS NOT NULL OR true",
        )
        for predicate in variations:
            with self.subTest(predicate=predicate), self.assertRaises(OwnerSchemaRejected):
                reviewed.require_matches(IndexShape("ix", ("uuid",), False, predicate))
        with self.assertRaises(OwnerSchemaRejected):
            IndexShape("ix", ("uuid",), False, "status IS NOT NULL").require_matches(
                IndexShape("ix", ("uuid",), False, "status() IS NOT NULL")
            )
