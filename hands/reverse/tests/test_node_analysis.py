"""Packaged Analysis/ELF workflow in a disposable rootless placement.

Bake this test into an acceptance image without replacing packaged runtime source.
Fixture signatures exercise the Node/SDK boundary, not Rauthy/Cedar acceptance.
Uploaded ELF files are parsed by pinned native engines and never executed.
"""

import asyncio
import base64
import hashlib
import json
import os
import struct
import time
import unittest
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, Tool
from pydantic import BaseModel, JsonValue, TypeAdapter
from radare2_hand.application.imports import (
    BinaryDeleted,
    BinaryListing,
    BinaryReceipt,
    ChunkReceipt,
    PendingUpload,
)
from reverse_hand.infrastructure.operation_wire import AnalysisOperationView
from reverse_hand.node_server import create_app
from starlette.applications import Starlette

from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
from node_protocol.effect import NodeEffectPermit, sign_permit
from node_protocol.module_effects import parse_request, resource_id

TOOLS = frozenset(
    {
        "radare2_import_start",
        "radare2_import_chunk",
        "radare2_import_finish",
        "radare2_import_abort",
        "radare2_list_binaries",
        "radare2_delete_binary",
        "radare2_binary_info",
        "radare2_functions",
        "radare2_disassemble",
        "radare2_strings",
        "radare2_xrefs",
    }
)


class RpcReply[Result: BaseModel](BaseModel):
    result: Result


class EngineCatalogueView(BaseModel):
    engine: Literal["ghidra", "radare2"]
    tools: tuple[Tool, ...]


class ProjectCreated(BaseModel):
    project_id: str


class StageCreated(BaseModel):
    stage_id: str


class StagedArtifact(BaseModel):
    path: str


class BinaryFacts(BaseModel):
    bintype: str
    bits: int
    arch: str


class BinaryInfo(BaseModel):
    bin: BinaryFacts


class NativeResult[Result](BaseModel):
    result: Result


class FunctionView(BaseModel):
    addr: int
    indegree: int = 0


class InstructionView(BaseModel):
    addr: int
    opcode: str


class StringView(BaseModel):
    string: str | None = None


class NativePage[Item](BaseModel):
    total: int
    items: tuple[Item, ...]


@dataclass(frozen=True)
class ProcessState:
    uid: int
    capabilities: int
    no_new_privileges: bool
    state: str

    @classmethod
    def read(cls, path: Path) -> "ProcessState":
        uid, capabilities, protected, state = -1, -1, False, ""
        for line in path.read_text().splitlines():
            field, _, value = line.partition(":")
            if field == "Uid":
                uid = int(value.split()[0])
            elif field == "CapEff":
                capabilities = int(value.strip(), 16)
            elif field == "NoNewPrivs":
                protected = value.strip() == "1"
            elif field == "State":
                state = value.strip()[0]
        return cls(uid, capabilities, protected, state)


def native_processes() -> tuple[ProcessState, ...]:
    result: list[ProcessState] = []
    for path in Path("/proc").glob("[0-9]*/status"):
        try:
            state = ProcessState.read(path)
        except (FileNotFoundError, ProcessLookupError):
            continue
        if state.uid == 1000 and state.state not in {"Z", "X"}:
            result.append(state)
    return tuple(result)


def payload[Result](result: CallToolResult, adapter: TypeAdapter[Result]) -> Result:
    value: JsonValue = TypeAdapter[JsonValue](JsonValue).validate_python(result.structured_content)
    while isinstance(value, dict) and set(value) == {"result"}:
        value = value["result"]
    if isinstance(value, str):
        return adapter.validate_json(value)
    return adapter.validate_python(value)


class UnifiedAnalysisTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.key = Ed25519PrivateKey.generate()
        self.actor, self.session = uuid4(), uuid4()
        self.spec = Deployment(
            id=uuid4(),
            node_uuid=uuid4(),
            project_uuid=uuid4(),
            release=ModuleRelease(
                module="reverse",
                image="registry.example/analysis@sha256:" + "a" * 64,
                lifecycle="sessionful",
            ),
            limits=ResourceLimits(memory_bytes=1536 * 1024**2, cpu_millis=750, pids=128),
            workspace=WorkspaceMount(id=uuid4()),
            effect_verify_key=self.key.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode(),
        )
        self.sequence = 0
        self.bearer = "Bearer native-radare2-fixture-not-provider-identity"

    def require_isolation(self) -> None:
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(os.statvfs("/").f_flag & os.ST_RDONLY)
        self.assertNotEqual(int(Path("/proc/self/uid_map").read_text().split()[1]), 0)
        self.assertEqual({path.name for path in Path("/sys/class/net").iterdir()}, {"lo"})
        facts = Path("/project-data").stat()
        self.assertEqual((facts.st_uid, facts.st_mode & 0o777), (1000, 0o700))

    async def frame(
        self,
        call: CallToolRequestParams | None = None,
        alter: Callable[[NodeEffectPermit], NodeEffectPermit] | None = None,
    ) -> httpx.Response:
        assert self.spec.workspace is not None
        self.sequence += 1
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self.sequence,
                "method": "tools/call" if call is not None else "tools/list",
                **({"params": call.model_dump(mode="json", exclude_none=True)} if call else {}),
            },
            separators=(",", ":"),
        ).encode()
        self.assertLessEqual(len(body), 32768)
        parsed, now = parse_request("reverse", body), int(time.time())
        evidence = NodeEffectPermit(
            module="reverse",
            node_uuid=self.spec.node_uuid,
            placement_uuid=self.spec.id,
            project_uuid=self.spec.project_uuid,
            workspace_uuid=self.spec.workspace.id,
            actor_uuid=self.actor,
            agent_session_uuid=self.session,
            request_uuid=uuid4(),
            grant_revision=1,
            fingerprint=self.spec.fingerprint,
            body_digest=hashlib.sha256(body).hexdigest(),
            bearer_digest=hashlib.sha256(self.bearer.encode()).hexdigest(),
            arguments_digest=parsed.arguments_digest,
            method="tools/call" if call else "tools/list",
            tool=parsed.tool,
            resource_id=resource_id(
                "reverse",
                self.spec.node_uuid,
                self.spec.project_uuid,
                self.spec.workspace.id,
            ),
            issued_at=now,
            expires_at=now + 5,
        )
        return await self.client.post(
            "/mcp",
            content=body,
            headers={
                "content-type": "application/json",
                "authorization": self.bearer,
                "accept": "application/json, text/event-stream",
                "mcp-protocol-version": "2025-11-25",
                "x-briareus-node-permit": sign_permit(
                    alter(evidence) if alter else evidence, self.key
                ),
            },
        )

    async def call(
        self,
        call: CallToolRequestParams,
        *,
        error: bool = False,
    ) -> CallToolResult:
        response = await self.frame(call)
        self.assertEqual(response.status_code, 200, response.text)
        result = RpcReply[CallToolResult].model_validate_json(response.content).result
        self.assertEqual(bool(result.is_error), error, result)
        return result

    async def radare(self, call: CallToolRequestParams, *, error: bool = False) -> CallToolResult:
        return await self.call(
            CallToolRequestParams(
                name="analysis_call",
                arguments={
                    "engine": "radare2",
                    "tool": call.name,
                    "arguments": call.arguments or {},
                },
            ),
            error=error,
        )

    async def check_catalogues(self) -> None:
        response = await self.frame()
        self.assertEqual(response.status_code, 200, response.text)
        catalogue = RpcReply[ListToolsResult].model_validate_json(response.content).result
        self.assertEqual(
            {item.name for item in catalogue.tools},
            {
                "analysis_tools",
                "analysis_call",
                "analysis_start",
                "analysis_poll",
                "analysis_cancel",
            },
        )
        self.assertEqual(len(catalogue.tools), 5)
        self.assertTrue(all(isinstance(item.input_schema, dict) for item in catalogue.tools))
        for engine in ("ghidra", "radare2"):
            described = await self.call(
                CallToolRequestParams(
                    name="analysis_tools",
                    arguments={"engine": engine},
                )
            )
            native = payload(described, TypeAdapter(EngineCatalogueView))
            self.assertEqual(native.engine, engine)
            self.assertTrue(native.tools)
            if engine == "radare2":
                self.assertEqual({item.name for item in native.tools}, TOOLS)
            else:
                await self.check_ghidra_read(native.tools)

    async def check_ghidra_read(self, tools: tuple[Tool, ...]) -> None:
        safe = next(
            (
                item.name
                for item in tools
                if item.name in {"list_projects", "list_active_programs", "check_connection"}
                and not item.input_schema.get("required")
            ),
            None,
        )
        self.assertIsNotNone(safe, "An actual bounded Ghidra runtime read is required")
        assert safe is not None
        checked = await self.call(
            CallToolRequestParams(
                name="analysis_call",
                arguments={
                    "engine": "ghidra",
                    "tool": safe,
                    "arguments": {},
                },
            )
        )
        self.assertTrue(checked.content)

    async def check_paused_owner(self, operation_id: str) -> None:
        await asyncio.sleep(3)
        states = await asyncio.to_thread(native_processes)
        self.assertTrue(states)
        self.assertTrue(all(value.state in {"T", "t"} for value in states), states)
        wrong = await self.frame(
            CallToolRequestParams(name="analysis_poll", arguments={"operation_id": operation_id}),
            lambda permit: permit.model_copy(update={"actor_uuid": uuid4()}),
        )
        self.assertEqual(wrong.status_code, 200, wrong.text)
        self.assertTrue(RpcReply[CallToolResult].model_validate_json(wrong.content).result.is_error)

    async def ghidra(self, call: CallToolRequestParams, *, pause: bool = False) -> CallToolResult:
        response = await self.frame(
            CallToolRequestParams(
                name="analysis_start",
                arguments={
                    "engine": "ghidra",
                    "tool": call.name,
                    "arguments": call.arguments or {},
                },
            ),
            (lambda permit: permit.model_copy(update={"expires_at": int(time.time()) + 2}))
            if pause
            else None,
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = RpcReply[CallToolResult].model_validate_json(response.content).result
        self.assertFalse(result.is_error, result)
        state = AnalysisOperationView.model_validate_json(json.dumps(result.structured_content))
        if pause:
            await self.check_paused_owner(state.operation_id)
        async with asyncio.timeout(100):
            while state.state == "running":
                polled = await self.call(
                    CallToolRequestParams(
                        name="analysis_poll",
                        arguments={"operation_id": state.operation_id},
                    )
                )
                state = AnalysisOperationView.model_validate_json(
                    json.dumps(polled.structured_content)
                )
                if state.state == "running":
                    await asyncio.sleep(0.5)
        self.assertEqual(state.state, "completed", state)
        self.assertIsNotNone(state.result)
        assert state.result is not None
        self.assertFalse(state.result.is_error, state.result)
        return state.result

    async def check_ghidra_import_and_decompile(self) -> None:
        project = payload(
            await self.ghidra(
                CallToolRequestParams(
                    name="create_project",
                    arguments={"name": "native-async-acceptance"},
                )
            ),
            TypeAdapter(ProjectCreated),
        )
        code = bytes([184, 7, 0, 0, 0, 195])
        tiny = (
            b"\x7fELF\x02\x01\x01"
            + bytes(9)
            + struct.pack("<HHIQQQIHHHHHH", 2, 62, 1, 0x400078, 64, 0, 0, 64, 56, 1, 0, 0, 0)
            + struct.pack("<IIQQQQQQ", 1, 5, 0, 0x400000, 0x400000, 126, 126, 0x1000)
            + code
        )
        self.assertEqual(len(tiny), 126)
        stage = payload(
            await self.ghidra(
                CallToolRequestParams(
                    name="artifact_stage_begin",
                    arguments={
                        "project_id": project.project_id,
                        "name": "native-async.elf",
                        "size_bytes": len(tiny),
                        "sha256": hashlib.sha256(tiny).hexdigest(),
                    },
                )
            ),
            TypeAdapter(StageCreated),
        )
        arguments = {"project_id": project.project_id, "stage_id": stage.stage_id}
        await self.ghidra(
            CallToolRequestParams(
                name="artifact_stage_write",
                arguments={
                    **arguments,
                    "offset": 0,
                    "data_base64": base64.b64encode(tiny).decode(),
                },
            )
        )
        staged = payload(
            await self.ghidra(
                CallToolRequestParams(
                    name="artifact_stage_finish",
                    arguments=arguments,
                )
            ),
            TypeAdapter(StagedArtifact),
        )
        await self.ghidra(
            CallToolRequestParams(
                name="import_file",
                arguments={
                    "project_id": project.project_id,
                    "file_path": staged.path,
                    "auto_analyze": True,
                },
            ),
            pause=True,
        )
        decompiled = await self.ghidra(
            CallToolRequestParams(
                name="get_high_level_behavior_view",
                arguments={
                    "project_id": project.project_id,
                    "action": "00400078",
                    "program": "native-async.elf",
                    "timeout": 60,
                },
            )
        )
        self.assertIn("7", decompiled.model_dump_json())
        await self.ghidra(CallToolRequestParams(name="artifact_stage_cancel", arguments=arguments))
        await self.ghidra(
            CallToolRequestParams(
                name="delete_project",
                arguments={"project_id": project.project_id},
            )
        )

    async def listing(self) -> BinaryListing:
        return payload(
            await self.radare(
                CallToolRequestParams(
                    name="radare2_list_binaries",
                    arguments={},
                )
            ),
            TypeAdapter(BinaryListing),
        )

    async def check_radare_import(self, elf: bytes) -> BinaryReceipt:
        self.assertEqual((await self.listing()).binaries, ())
        digest = hashlib.sha256(elf).hexdigest()
        pending = payload(
            await self.radare(
                CallToolRequestParams(
                    name="radare2_import_start",
                    arguments={
                        "name": "native-true.elf",
                        "sha256": digest,
                        "size": len(elf),
                    },
                )
            ),
            TypeAdapter(PendingUpload),
        )
        self.assertEqual(pending.chunk_bytes, 12288)
        for offset in range(0, len(elf), pending.chunk_bytes):
            chunk = elf[offset : offset + pending.chunk_bytes]
            receipt = payload(
                await self.radare(
                    CallToolRequestParams(
                        name="radare2_import_chunk",
                        arguments={
                            "upload_id": str(pending.upload_id),
                            "offset": offset,
                            "content_base64": base64.b64encode(chunk).decode(),
                        },
                    )
                ),
                TypeAdapter(ChunkReceipt),
            )
            self.assertEqual(receipt.offset, offset + len(chunk))
        committed = payload(
            await self.radare(
                CallToolRequestParams(
                    name="radare2_import_finish",
                    arguments={"upload_id": str(pending.upload_id)},
                )
            ),
            TypeAdapter(BinaryReceipt),
        )
        self.assertEqual((committed.sha256, committed.size), (digest, len(elf)))
        self.assertEqual((await self.listing()).binaries, (committed,))
        return committed

    async def check_radare_inspection(self, binary: BinaryReceipt) -> None:
        arguments = {"binary_id": str(binary.binary_id)}
        info = payload(
            await self.radare(
                CallToolRequestParams(
                    name="radare2_binary_info",
                    arguments=arguments,
                )
            ),
            TypeAdapter(NativeResult[BinaryInfo]),
        ).result.bin
        self.assertEqual(info.bintype, "elf")
        self.assertIn(info.bits, {32, 64})
        self.assertTrue(info.arch)
        functions = payload(
            await self.radare(
                CallToolRequestParams(
                    name="radare2_functions",
                    arguments={**arguments, "limit": 100},
                )
            ),
            TypeAdapter(NativePage[FunctionView]),
        )
        self.assertGreater(functions.total, 0)
        self.assertTrue(functions.items)
        function = next((item for item in functions.items if item.indegree > 0), None)
        self.assertIsNotNone(function, "Real ELF analysis must discover an inbound reference")
        assert function is not None
        address = hex(function.addr)
        instructions = payload(
            await self.radare(
                CallToolRequestParams(
                    name="radare2_disassemble",
                    arguments={**arguments, "address": address, "count": 8},
                )
            ),
            TypeAdapter(NativeResult[tuple[InstructionView, ...]]),
        ).result
        self.assertTrue(instructions)
        self.assertTrue(all(item.opcode for item in instructions))
        strings = payload(
            await self.radare(
                CallToolRequestParams(
                    name="radare2_strings",
                    arguments={**arguments, "limit": 20},
                )
            ),
            TypeAdapter(NativePage[StringView]),
        )
        self.assertGreater(strings.total, 0)
        self.assertTrue(any(item.string for item in strings.items))
        xrefs = await self.radare(
            CallToolRequestParams(
                name="radare2_xrefs",
                arguments={**arguments, "address": address},
            )
        )
        self.assertTrue(payload(xrefs, TypeAdapter(NativeResult[list[JsonValue]])).result)

    async def check_rejections(self, binary: BinaryReceipt, elf: bytes) -> None:
        invalid = (
            CallToolRequestParams(
                name="radare2_import_start",
                arguments={
                    "name": "../escape",
                    "sha256": binary.sha256,
                    "size": len(elf),
                },
            ),
            CallToolRequestParams(
                name="radare2_binary_info", arguments={"binary_id": "/etc/passwd"}
            ),
            CallToolRequestParams(
                name="radare2_binary_info", arguments={"binary_id": str(uuid4())}
            ),
            CallToolRequestParams(
                name="radare2_disassemble",
                arguments={
                    "binary_id": str(binary.binary_id),
                    "address": "0x0;!id",
                    "count": 8,
                },
            ),
            CallToolRequestParams(name="radare2_arbitrary_command", arguments={"command": "!id"}),
        )
        for call in invalid:
            await self.radare(call, error=True)
        await self.call(
            CallToolRequestParams(
                name="radare2_arbitrary_command",
                arguments={"command": "!id"},
            ),
            error=True,
        )
        await self.call(
            CallToolRequestParams(
                name="analysis_call",
                arguments={
                    "engine": "unknown",
                    "tool": "radare2_list_binaries",
                    "arguments": {},
                },
            ),
            error=True,
        )
        changes: tuple[Callable[[NodeEffectPermit], NodeEffectPermit], ...] = (
            lambda permit: permit.model_copy(update={"workspace_uuid": uuid4()}),
            lambda permit: permit.model_copy(update={"project_uuid": uuid4()}),
            lambda permit: permit.model_copy(update={"module": "terminal"}),
            lambda permit: permit.model_copy(update={"expires_at": int(time.time()) - 1}),
        )
        for alter in changes:
            denied = await self.frame(alter=alter)
            self.assertEqual(denied.status_code, 403, denied.text)
        self.assertEqual((await self.listing()).binaries, (binary,))

    async def check_bad_hash_and_cleanup(self, binary: BinaryReceipt, elf: bytes) -> None:
        bad = payload(
            await self.radare(
                CallToolRequestParams(
                    name="radare2_import_start",
                    arguments={
                        "name": "bad-hash.elf",
                        "sha256": "0" * 64,
                        "size": 4,
                    },
                )
            ),
            TypeAdapter(PendingUpload),
        )
        await self.radare(
            CallToolRequestParams(
                name="radare2_import_chunk",
                arguments={
                    "upload_id": str(bad.upload_id),
                    "offset": 0,
                    "content_base64": base64.b64encode(elf[:4]).decode(),
                },
            )
        )
        await self.radare(
            CallToolRequestParams(
                name="radare2_import_finish",
                arguments={"upload_id": str(bad.upload_id)},
            ),
            error=True,
        )
        await self.radare(
            CallToolRequestParams(
                name="radare2_import_abort",
                arguments={"upload_id": str(bad.upload_id)},
            )
        )
        self.assertEqual((await self.listing()).binaries, (binary,))
        deleted = payload(
            await self.radare(
                CallToolRequestParams(
                    name="radare2_delete_binary",
                    arguments={"binary_id": str(binary.binary_id)},
                )
            ),
            TypeAdapter(BinaryDeleted),
        )
        self.assertEqual(deleted.state, "deleted")
        self.assertEqual((await self.listing()).binaries, ())

    async def test_one_facade_native_elf_and_private_storage_boundary(self) -> None:
        await asyncio.to_thread(self.require_isolation)
        elf = await asyncio.to_thread(Path("/usr/bin/true").read_bytes)
        self.assertTrue(elf.startswith(b"\x7fELF"))
        app = create_app(self.spec)
        assert isinstance(app.app, Starlette)
        async with (
            app.app.router.lifespan_context(app.app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app),
                base_url="http://" + self.spec.container_name + ".reverse",
            ) as client,
        ):
            self.client = client
            await self.check_catalogues()
            await self.check_ghidra_import_and_decompile()
            execution = await asyncio.to_thread(native_processes)
            self.assertTrue(execution)
            self.assertTrue(
                all(item.capabilities == 0 and item.no_new_privileges for item in execution)
            )
            binary = await self.check_radare_import(elf)
            await self.check_radare_inspection(binary)
            await self.check_rejections(binary, elf)
            await self.check_bad_hash_and_cleanup(binary, elf)
