"""Original operation and authority lifetime cannot be substituted by a proof."""

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from modules.project_runtime.domain.source_proof import (
    AuthorityEpochs,
    AuthorityVersions,
    EffectSubject,
    ResourceVersions,
    SourceProof,
    SourceProofMismatch,
    SourceProofRequirement,
)


def requirement() -> SourceProofRequirement:
    operation_uuid = uuid4()
    owner_uuid = uuid4()
    return SourceProofRequirement(
        subject=EffectSubject(
            "files",
            "briareus:files",
            "files.write.reserve",
            str(operation_uuid),
            "a" * 64,
            uuid4(),
            uuid4(),
            uuid4(),
            owner_uuid,
            uuid4(),
            operation_uuid,
        ),
        versions=AuthorityVersions(1, 2, 3),
        epochs=AuthorityEpochs(uuid4(), uuid4(), uuid4()),
        owner_scope="project",
        owner_uuid=owner_uuid,
        recipient_expires_at=datetime.now(UTC) + timedelta(seconds=10),
        grant_expires_at=datetime.now(UTC) + timedelta(seconds=8),
    )


def proof(expected: SourceProofRequirement) -> SourceProof:
    return SourceProof(
        expected.subject,
        expected.versions,
        expected.epochs,
        ResourceVersions(5, None, None, None),
        expected.grant_expires_at - timedelta(seconds=1),
    )


class SourceProofTests(unittest.TestCase):
    def test_dispatch_binds_every_subject_field(self) -> None:
        expected = requirement()
        observed = proof(expected)
        observed.require_for(expected)
        substitutions = (
            replace(observed.subject, owner="runtime"),
            replace(observed.subject, audience="briareus:runtime"),
            replace(observed.subject, operation="files.write.dispatch"),
            replace(observed.subject, idempotency_key=str(uuid4())),
            replace(observed.subject, payload_sha256="b" * 64),
            replace(observed.subject, recipient_service_uuid=uuid4()),
            replace(observed.subject, recipient_instance_uuid=uuid4()),
            replace(observed.subject, actor_uuid=uuid4()),
            replace(observed.subject, project_uuid=uuid4()),
            replace(observed.subject, session_uuid=uuid4()),
            replace(observed.subject, operation_uuid=uuid4()),
        )
        for subject in substitutions:
            with self.subTest(subject=subject), self.assertRaises(SourceProofMismatch):
                replace(observed, subject=subject).require_for(expected)

    def test_each_authority_revision_and_epoch_is_bound(self) -> None:
        expected = requirement()
        observed = proof(expected)
        for versions in (
            replace(observed.versions, identity=2),
            replace(observed.versions, control=3),
            replace(observed.versions, access=4),
        ):
            with self.subTest(versions=versions), self.assertRaises(SourceProofMismatch):
                replace(observed, versions=versions).require_for(expected)
        for epochs in (
            replace(observed.epochs, identity=uuid4()),
            replace(observed.epochs, platform=uuid4()),
            replace(observed.epochs, access=uuid4()),
        ):
            with self.subTest(epochs=epochs), self.assertRaises(SourceProofMismatch):
                replace(observed, epochs=epochs).require_for(expected)

    def test_team_requires_owner_and_both_current_revisions(self) -> None:
        expected = replace(requirement(), owner_scope="team", owner_uuid=uuid4())
        observed = replace(
            proof(expected), resources=ResourceVersions(5, expected.owner_uuid, 2, 3)
        )
        observed.require_for(expected)
        for resources in (
            replace(observed.resources, team_uuid=uuid4()),
            replace(observed.resources, team=None),
            replace(observed.resources, team_resource=None),
        ):
            with self.subTest(resources=resources), self.assertRaises(SourceProofMismatch):
                replace(observed, resources=resources).require_for(expected)

    def test_personal_project_cannot_acquire_team_authority(self) -> None:
        expected = requirement()
        for resources in (
            ResourceVersions(5, uuid4(), 2, 3),
            ResourceVersions(5, None, 2, None),
            ResourceVersions(5, None, None, 3),
        ):
            with self.subTest(resources=resources), self.assertRaises(SourceProofMismatch):
                replace(proof(expected), resources=resources).require_for(expected)

    def test_status_retains_original_resource_revisions(self) -> None:
        expected = requirement()
        observed = proof(expected)
        status = replace(expected, resources=observed.resources)
        observed.require_for(status)
        # First dispatch learns the producer-owned resource revision, while
        # inspection must remain bound to the original command's revision.
        changed = replace(observed, resources=replace(observed.resources, control=6))
        changed.require_for(expected)
        with self.assertRaises(SourceProofMismatch):
            changed.require_for(status)

    def test_lifetime_cannot_exceed_either_authority(self) -> None:
        expected = requirement()
        observed = proof(expected)
        for grant_seconds, peer_seconds in ((-1, 1), (1, -1)):
            limited = replace(
                expected,
                grant_expires_at=observed.expires_at + timedelta(seconds=grant_seconds),
                recipient_expires_at=observed.expires_at + timedelta(seconds=peer_seconds),
            )
            with self.subTest(limited=limited), self.assertRaises(SourceProofMismatch):
                observed.require_for(limited)
