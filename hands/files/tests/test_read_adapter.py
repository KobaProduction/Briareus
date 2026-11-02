"""Focused consumer checks; no real grant, user token or filesystem read.

"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import FrozenInstanceError
from unittest import TestCase

from files_hand._read_adapter import (
    FilesMcpReadUnavailable,
    FilesReadArguments,
    FilesReadContent,
)
from pydantic import JsonValue, TypeAdapter


def check_arguments() -> None:
    bad: tuple[JsonValue, ...] = (
        None,
        {},
        [],
        {"path": ""},
        {"path": "."},
        {"path": ".."},
        {"path": "../secret"},
        {"path": "/var/run/secrets"},
        {"path": "a//b"},
        {"path": "dir/./file"},
        {"path": "a\\b"},
        {"path": "a\x00b"},
        {"path": "a\ud800"},
        {"path": "line\nbreak"},
        {"path": "a" * 256},
        {"path": "é" * 128},
        {"path": "a/" * 64 + "b"},
        {"path": "file", "max_bytes": False},
        {"path": "file", "max_bytes": 0},
        {"path": "file", "max_bytes": 262145},
        {"path": "file", "max_bytes": 2.0},
        {"path": "file", "max_bytes": "16"},
        {"path": "file", "grant": True},
        {"path": "file", "project_uuid": "untrusted-selector"},
        {"path": ".upload-" + "a" * 32 + ".tmp"},
        {"path": "e\u0301.txt"},
    )
    for arguments in bad:
        try:
            FilesReadArguments.parse(arguments)
        except FilesMcpReadUnavailable:
            pass
        else:
            raise AssertionError("untrusted read input accepted")
    # Direct construction must not skip the parser's path or byte budget.
    for path, budget in (("../secret", 1), ("file", True), ("file", 262145)):
        try:
            FilesReadArguments(path=path, max_bytes=budget)
        except FilesMcpReadUnavailable:
            pass
        else:
            raise AssertionError("unsafe internal read DTO accepted")
    request = FilesReadArguments.parse({"path": "документы/отчёт.bin"})
    canonical = request.canonical_arguments()
    assert canonical.path == request.path and canonical.max_bytes == 262_144
    TestCase().assertRaises(FrozenInstanceError, setattr, canonical, "path", "another-file")
    assert request.path == "документы/отчёт.bin"
    assert FilesReadArguments.parse({"path": "%2e%2e/literal"}).path == "%2e%2e/literal"
    for payload in (b"", b"\x00\xffunit-fixture", b"x" * 262_144):
        result = FilesReadContent.from_verified_bytes(request, payload)
        assert base64.b64decode(result.content_base64, validate=True) == payload
        assert result.sha256 == hashlib.sha256(payload).hexdigest()
        assert result.size_bytes == len(payload)
        assert "content_base64=" not in repr(result)
        # The Frontend's current read-result decoder accepts exactly this
        # shape; no Cedar/credential/owner private diagnostics belong here.
        content = result.content_payload()
        assert content is result
        wire = json.loads(TypeAdapter(FilesReadContent).dump_json(content))
        assert set(wire) == {"path", "size_bytes", "sha256", "content_base64"}
        assert wire["path"] == request.path
        assert wire["size_bytes"] == len(payload)
        assert wire["sha256"] == hashlib.sha256(payload).hexdigest()
        assert base64.b64decode(wire["content_base64"], validate=True) == payload
        assert "access_token" not in wire and "resource_revision" not in wire
    for invalid_payload in (bytearray(b"x"), "not-bytes", b"x" * 262_145):
        TestCase().assertRaisesRegex(
            FilesMcpReadUnavailable, "FILES_READ_RESULT_INVALID",
            FilesReadContent.from_verified_bytes, request, invalid_payload,
        )


async def main() -> None:
    check_arguments()
    print("FILES_READ_CONSUMER_CHECKS_PASS_NOT_A_PERMIT_OR_MCP_ACCEPTANCE")


if __name__ == "__main__":
    asyncio.run(main())
