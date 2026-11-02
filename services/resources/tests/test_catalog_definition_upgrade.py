"""Only the explicitly reviewed Analysis source-closure addition is eligible."""

import unittest
from dataclasses import replace

from projects.domain.module_catalog import BuildInputs, StoredArtifact, reviewed_upgrade
from projects.infrastructure.catalog_records import artifact_definition

from node_protocol.catalog import ARTIFACTS


class DefinitionUpgradeTests(unittest.TestCase):
    def previous(self) -> StoredArtifact:
        inputs = artifact_definition(ARTIFACTS["reverse"]).inputs
        previous = replace(
            inputs,
            paths=tuple(
                path for path in inputs.paths if path != "hands/radare2/src/radare2_hand/**"
            ),
        )
        return StoredArtifact("reverse", True, previous)

    def test_exact_old_analysis_definition_is_eligible_without_changing_image_pins(self) -> None:
        definition = artifact_definition(ARTIFACTS["reverse"])
        artifact = self.previous()
        self.assertTrue(reviewed_upgrade(artifact, definition))
        self.assertIsNotNone(artifact.inputs)
        if artifact.inputs is None:
            self.fail("Fixture must include the previous reviewed inputs")
        self.assertEqual(artifact.inputs.build_args, definition.inputs.build_args)
        self.assertFalse(reviewed_upgrade(replace(artifact, inputs=definition.inputs), definition))

    def test_unknown_changes_disabled_or_other_artifacts_still_fail_closed(self) -> None:
        definition = artifact_definition(ARTIFACTS["reverse"])
        artifact = self.previous()
        inputs: BuildInputs = definition.inputs if artifact.inputs is None else artifact.inputs
        changed = replace(inputs, build_args=(("RADARE2_IMAGE", "foreign/image"),))
        self.assertFalse(reviewed_upgrade(replace(artifact, inputs=changed), definition))
        self.assertFalse(reviewed_upgrade(replace(artifact, enabled=False), definition))
        self.assertFalse(
            reviewed_upgrade(replace(artifact, key="web"), artifact_definition(ARTIFACTS["web"]))
        )
