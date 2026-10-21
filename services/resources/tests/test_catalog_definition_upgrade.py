"""Only the explicitly reviewed Analysis source-closure addition is eligible."""
import unittest
from copy import deepcopy
from types import SimpleNamespace
from node_protocol.catalog import ARTIFACTS
from projects.module_catalog import reviewed_input_upgrade

class DefinitionUpgradeTests(unittest.TestCase):
    def previous(self):
        value=deepcopy(ARTIFACTS["reverse"].inputs)
        value["paths"].remove("hands/radare2/src/radare2_hand/**")
        return SimpleNamespace(key="reverse",inputs=value,enabled=True)

    def test_exact_old_analysis_definition_is_upgraded_without_touching_image_pins(self):
        artifact=self.previous()
        pins=deepcopy(artifact.inputs["build_args"])
        self.assertTrue(reviewed_input_upgrade(artifact,ARTIFACTS["reverse"]))
        self.assertEqual(artifact.inputs,ARTIFACTS["reverse"].inputs)
        self.assertEqual(artifact.inputs["build_args"],pins)
        self.assertFalse(reviewed_input_upgrade(artifact,ARTIFACTS["reverse"]))

    def test_unknown_changes_disabled_or_other_artifacts_still_fail_closed(self):
        artifact=self.previous();artifact.inputs["build_args"]["RADARE2_IMAGE"]="foreign/image"
        self.assertFalse(reviewed_input_upgrade(artifact,ARTIFACTS["reverse"]))
        artifact=self.previous();artifact.enabled=False
        self.assertFalse(reviewed_input_upgrade(artifact,ARTIFACTS["reverse"]))
        artifact=self.previous();artifact.key="web"
        self.assertFalse(reviewed_input_upgrade(artifact,ARTIFACTS["web"]))
