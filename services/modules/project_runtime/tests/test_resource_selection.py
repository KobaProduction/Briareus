"""Selectors preserve current scope, ambiguity, and the authority boundary."""

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from modules.project_runtime.authorization import (
    ProjectAccessDenied,
    ProjectAction,
    ProjectInvocation,
    ProjectPermit,
    ProjectRuntimeAuthority,
)
from modules.project_runtime.domain.resource_query import (
    ResourceQuery,
    ResourceSelectionError,
    effective_collection,
    one_named_resource,
)
from modules.project_runtime.domain.resources import integration_action
from modules.project_runtime.integrations import ProjectIntegrationError
from modules.project_runtime.resource_scope import EffectiveResourceScope
from modules.project_runtime.variables import (
    ProjectVariableError,
    ProjectVariableRef,
    ProjectVariableSelector,
)


def scope(project_uuid: UUID) -> EffectiveResourceScope:
    return EffectiveResourceScope(project_uuid, project_uuid, None, None, 1, "a" * 64)


def variable(project_uuid: UUID, name: str = "api_key") -> ProjectVariableRef:
    return ProjectVariableRef(scope(project_uuid), uuid4(), "secret", name)


class VariableResolver:
    def __init__(self, records: tuple[ProjectVariableRef, ...]) -> None:
        self.records = records
        self.calls = 0

    async def list_effective_metadata(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
    ) -> tuple[ProjectVariableRef, ...]:
        if invocation.project_id != permit.project_id:
            raise AssertionError("resolver received another project")
        self.calls += 1
        return self.records

    async def resolve_metadata(
        self,
        invocation: ProjectInvocation,
        *,
        variable_id: UUID,
        permit: ProjectPermit,
    ) -> ProjectVariableRef:
        if invocation.project_id != permit.project_id:
            raise AssertionError("resolver received another project")
        self.calls += 1
        return next(record for record in self.records if record.variable_id == variable_id)


class CurrentAuthority:
    def __init__(self, permit: ProjectPermit) -> None:
        self.permit = permit
        self.calls: list[ProjectAction] = []

    async def require(self, invocation: ProjectInvocation, action: ProjectAction) -> ProjectPermit:
        if invocation.project_id != self.permit.project_id:
            raise AssertionError("authority received another project")
        self.calls.append(action)
        return self.permit


class ResourceSelectionTests(unittest.TestCase):
    def test_filtered_stale_resource_still_denies_entire_collection(self) -> None:
        project_uuid = uuid4()
        current = variable(project_uuid)
        stale = replace(current, scope=replace(current.scope, project_access_revision="b" * 64))
        with self.assertRaises(ResourceSelectionError) as raised:
            effective_collection(
                (current, stale),
                project_id=project_uuid,
                access_revision="a" * 64,
                query=ResourceQuery("team"),
            )
        self.assertEqual(raised.exception.code, "RESOURCE_ACCESS_STALE")

    def test_duplicate_team_project_alias_stays_ambiguous(self) -> None:
        project_uuid, team_uuid = uuid4(), uuid4()
        personal = variable(project_uuid)
        inherited = replace(
            personal,
            variable_id=uuid4(),
            scope=replace(
                personal.scope,
                owner_project_id=None,
                owner_team_id=team_uuid,
                project_owner_team_id=team_uuid,
            ),
        )
        records = effective_collection(
            (personal, inherited),
            project_id=project_uuid,
            access_revision="a" * 64,
            query=ResourceQuery(),
        )
        self.assertEqual(records, (personal, inherited))
        with self.assertRaises(ResourceSelectionError) as raised:
            one_named_resource(records, name="API_KEY")
        self.assertEqual(raised.exception.code, "RESOURCE_NAME_AMBIGUOUS")

    def test_metadata_cannot_escape_selected_project(self) -> None:
        record = variable(uuid4())
        with self.assertRaises(ProjectVariableError) as raised:
            record.require_access(project_uuid=uuid4(), access_revision="a" * 64)
        self.assertEqual(raised.exception.code, "PROJECT_VARIABLE_ACCESS_DENIED")

    def test_infrastructure_provider_write_remains_unavailable(self) -> None:
        self.assertEqual(integration_action("coolify", "read"), "infrastructure.read")
        with self.assertRaises(ProjectIntegrationError) as raised:
            integration_action("coolify", "write")
        self.assertEqual(raised.exception.code, "PROJECT_INTEGRATION_WRITE_UNAVAILABLE")


class ResourceApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_authority_denies_before_provider(self) -> None:
        project_uuid = uuid4()
        resolver = VariableResolver((variable(project_uuid),))
        invocation = ProjectInvocation(project_uuid, uuid4())
        selector = ProjectVariableSelector(ProjectRuntimeAuthority(), resolver)
        with self.assertRaises(ProjectAccessDenied):
            await selector.list_metadata(invocation)
        self.assertEqual(resolver.calls, 0)

    async def test_named_metadata_selection_refreshes_authority_and_keeps_secret_metadata(
        self,
    ) -> None:
        project_uuid, session_uuid = uuid4(), uuid4()
        record = variable(project_uuid)
        permit = ProjectPermit(
            project_uuid,
            uuid4(),
            session_uuid,
            "resources.use",
            datetime.now(UTC) + timedelta(seconds=5),
            1,
            "a" * 64,
        )
        authority = CurrentAuthority(permit)
        resolver = VariableResolver((record,))
        selector = ProjectVariableSelector(authority, resolver)
        invocation = ProjectInvocation(project_uuid, session_uuid)
        self.assertEqual(await selector.select_by_name(invocation, name="API_KEY"), record)
        self.assertEqual(authority.calls, ["resources.use"])
        self.assertEqual(resolver.calls, 1)
        self.assertFalse(hasattr(record, "value"))
