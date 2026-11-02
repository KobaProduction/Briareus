"""Native inventory cannot free missing capacity or adopt orphan components."""

import json
import unittest
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

from node_agent.application.inventory import ObserveInventory
from node_agent.domain.inventory import (
    Allocation,
    InventoryInvalid,
    ManagedComponent,
    egress_name,
)
from node_agent.infrastructure.container_models import ContainerInspection, ContainerSummary
from node_agent.infrastructure.inventory import (
    DockerComponentInventory,
    egress_quota,
)
from node_agent.runtime_profiles import EGRESS_REQUIRED, ROLE_LABEL


@dataclass
class ComponentFixture:
    components: tuple[ManagedComponent, ...]
    requested: UUID | None = None

    async def read(self, node_uuid: UUID) -> tuple[ManagedComponent, ...]:
        self.requested = node_uuid
        return self.components


@dataclass
class NativeFixture:
    inspection: str | None

    async def containers(self, node_uuid: UUID) -> tuple[ContainerSummary, ...]:
        del node_uuid
        return (ContainerSummary(identity="native"),)

    async def inspect(self, container_id: str) -> ContainerInspection | None:
        del container_id
        return (
            ContainerInspection.model_validate_json(self.inspection)
            if self.inspection is not None
            else None
        )


class InventoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.node_uuid = uuid4()
        self.main = ManagedComponent(
            "main",
            "briareus-" + "a" * 48,
            uuid4(),
            "b" * 64,
            Allocation(256 * 1024**2, 500, 128),
            "main",
            True,
            True,
            True,
        )
        self.helper = replace(
            self.main,
            container_id="helper",
            name=egress_name(self.main.name),
            allocation=egress_quota(),
            role="egress",
            requires_egress=False,
        )
        self.port = ComponentFixture((self.main, self.helper))
        self.use_case = ObserveInventory(self.port, egress_quota())

    async def test_complete_placement_aggregates_components(self) -> None:
        result = await self.use_case.execute(self.node_uuid)
        self.assertEqual(self.port.requested, self.node_uuid)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].allocation, self.main.allocation.plus(self.helper.allocation))
        self.assertTrue(result[0].running)
        self.assertTrue(result[0].ready)

    async def test_missing_helper_keeps_full_quota_and_blocks_readiness(self) -> None:
        self.port.components = (self.main,)
        result = await self.use_case.execute(self.node_uuid)
        self.assertEqual(result[0].allocation, self.main.allocation.plus(self.helper.allocation))
        self.assertFalse(result[0].running)
        self.assertFalse(result[0].ready)

    async def test_orphan_helper_is_accounted_and_never_adopted(self) -> None:
        self.port.components = (self.helper,)
        result = await self.use_case.execute(self.node_uuid)
        self.assertEqual(result[0].allocation, self.helper.allocation)
        self.assertFalse(result[0].running)
        self.assertFalse(result[0].ready)

    async def test_duplicate_or_foreign_helpers_fail_closed(self) -> None:
        for helpers in (
            (self.helper, self.helper),
            (replace(self.helper, deployment_uuid=uuid4()),),
            (replace(self.helper, fingerprint="c" * 64),),
        ):
            with self.subTest(helpers=helpers), self.assertRaises(InventoryInvalid):
                self.port.components = (self.main, *helpers)
                await self.use_case.execute(self.node_uuid)

    async def test_offline_module_does_not_reserve_a_companion(self) -> None:
        self.port.components = (replace(self.main, requires_egress=False),)
        result = await self.use_case.execute(self.node_uuid)
        self.assertEqual(result[0].allocation, self.main.allocation)
        self.assertTrue(result[0].ready)

    async def test_unhealthy_helper_prevents_complete_readiness(self) -> None:
        self.port.components = (self.main, replace(self.helper, ready=False))
        result = await self.use_case.execute(self.node_uuid)
        self.assertFalse(result[0].ready)
        self.assertTrue(result[0].running)

    async def test_disappeared_native_instance_is_not_reported(self) -> None:
        result = await DockerComponentInventory(NativeFixture(None)).read(self.node_uuid)
        self.assertEqual(result, ())

    async def test_unverified_native_resource_limits_are_rejected(self) -> None:
        for payload in ({}, {"Id": "native", "HostConfig": {"Memory": 0}}):
            with self.subTest(payload=payload), self.assertRaises(InventoryInvalid):
                await DockerComponentInventory(NativeFixture(json.dumps(payload))).read(
                    self.node_uuid
                )

    async def test_native_helper_isolation_and_metadata_are_verified(self) -> None:
        quota = egress_quota()
        for overrides in (
            {},
            {"Binds": ["/host:/secret"]},
            {"Privileged": True},
            {"ReadonlyRootfs": False},
        ):
            inspection = ContainerInspection.model_validate(
                {
                    "Id": "helper",
                    "Name": "/" + self.helper.name,
                    "Config": {
                        "User": "1000:1000",
                        "Labels": {
                            "io.briareus.deployment": str(self.main.deployment_uuid),
                            "io.briareus.spec": self.main.fingerprint,
                            ROLE_LABEL: "egress",
                            EGRESS_REQUIRED: "false",
                        },
                    },
                    "HostConfig": {
                        "Memory": quota.memory_bytes,
                        "NanoCpus": quota.cpu_millis * 1_000_000,
                        "PidsLimit": quota.pids,
                        "ReadonlyRootfs": True,
                        **overrides,
                    },
                    "State": {"Running": True, "Health": {"Status": "healthy"}},
                }
            )
            reader = DockerComponentInventory(
                NativeFixture(inspection.model_dump_json(by_alias=True))
            )
            if overrides:
                with self.assertRaises(InventoryInvalid):
                    await reader.read(self.node_uuid)
            else:
                result = await reader.read(self.node_uuid)
                self.assertEqual(result, (self.helper,))
