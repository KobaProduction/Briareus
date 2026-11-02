"""Terminal owner history remains immutable while verified rollback repairs projection."""

import unittest
from dataclasses import replace
from uuid import uuid4

from projects.application.placement_reconciliation import reconcile_receipt
from projects.domain.placement_reconciliation import (
    NodeObservation,
    OperationReceipt,
    OperationState,
    PlacementIdentity,
    RetainedDeployment,
    RuntimeRestoration,
    restoration_allowed,
)


class PlacementReconciliationPolicyTests(unittest.TestCase):
    def test_terminal_recovery_repairs_projection_without_rewriting_operation(self) -> None:
        operation = OperationState(uuid4(), 7, "failed", "UPDATE_FAILED")
        receipt = OperationReceipt(operation.operation_uuid, 7, "failed", "UPDATE_FAILED")
        decision = reconcile_receipt(
            operation,
            receipt,
            placement_sequence=7,
            restoration_verified=True,
            restoration_changes_projection=True,
            diagnostic_changed=False,
            first_diagnostic=False,
        )
        self.assertTrue(decision.terminal)
        self.assertFalse(decision.update_operation)
        self.assertFalse(decision.apply_desired_release)
        self.assertEqual(decision.placement_state, "ready")
        self.assertTrue(decision.restore_limits)
        self.assertTrue(decision.audit)

    def test_terminal_replay_is_quiet_until_first_diagnostic_is_available(self) -> None:
        operation = OperationState(uuid4(), 7, "failed", "UPDATE_FAILED")
        receipt = OperationReceipt(operation.operation_uuid, 7, "failed", "UPDATE_FAILED")
        for first_diagnostic in (False, True):
            decision = reconcile_receipt(
                operation,
                receipt,
                placement_sequence=7,
                restoration_verified=False,
                restoration_changes_projection=False,
                diagnostic_changed=first_diagnostic,
                first_diagnostic=first_diagnostic,
            )
            self.assertEqual(decision.audit, first_diagnostic)
            self.assertIsNone(decision.placement_state)
            self.assertFalse(decision.restore_limits)

    def test_changed_terminal_receipt_and_stale_operation_cannot_project(self) -> None:
        operation = OperationState(uuid4(), 7, "failed", "ROLLBACK_FAILED")
        receipt = OperationReceipt(operation.operation_uuid, 7, "failed", "UPDATE_FAILED")
        with self.assertRaisesRegex(ValueError, "Terminal operation receipt changed"):
            receipt.validate_for(operation, 7)
        with self.assertRaisesRegex(ValueError, "Operation no longer current"):
            replace(receipt, error="ROLLBACK_FAILED").validate_for(operation, 8)

    def test_restoration_requires_unambiguous_fresh_exact_owner_evidence(self) -> None:
        placement = PlacementIdentity(uuid4(), uuid4(), uuid4(), "svc", uuid4())
        previous = RetainedDeployment(placement, True, "fingerprint")
        node = NodeObservation(placement.node_uuid, 17, True, False)
        inventory = RuntimeRestoration(node.node_uuid, 17, True, 1, True, True, "fingerprint", True)
        self.assertTrue(restoration_allowed(placement, node.node_uuid, previous, node, inventory))
        invalid = (
            replace(inventory, matching_count=2),
            replace(inventory, sequence=16),
            replace(inventory, running=False),
            replace(inventory, ready=False),
            replace(inventory, fingerprint="other"),
            replace(inventory, limits_match=False),
        )
        for evidence in invalid:
            self.assertFalse(
                restoration_allowed(placement, node.node_uuid, previous, node, evidence)
            )
        other_scope = replace(previous, identity=replace(placement, project_uuid=uuid4()))
        self.assertFalse(
            restoration_allowed(placement, node.node_uuid, other_scope, node, inventory)
        )
