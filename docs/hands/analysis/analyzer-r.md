# Analyzer-R — Briareus radare2 proxy and native tool prerequisites

**Owner:** [V1 analysis Hands](../analysis.md),
[Analyzer-R](../../../services/hands/analysis/README.md),
[native radare2](../../../services/hands/radare2/README.md).
Analyzer-R and native radare2 are *separate deployments*.
This guide describes **tool prerequisites and provider errors**, not
the universal methodology of program analysis.

## Initial open and program identity

The native engine requires `open_file(file_path=absolute_path)`
before file-dependent operations, including `list_files`.
The path must be in the engine's permitted filesystem and the selected
project's actual artifact location; do not guess a path from a UI label.

1. Identify the binary and verify its hash/version, ISA, file format and
   mapping context. Use `open_file` for the intended absolute file.
   For raw/headerless files, review optional architecture/base-address
   overrides; do not invent a loader mapping.
2. After a successful open, inspect `show_info`, `list_sections`,
   `list_entrypoints` and relevant imports/exports.
3. Use `analyze(level, timeout_seconds)` within a bounded analysis scope,
   then `list_functions` and available symbol/xref queries.
4. Discover available decompiler backends using `list_decompilers`
   before `use_decompiler`. `decompile_function(address)` supports
   cursor pagination; preserve cursors on large outputs. Use targeted
   `disassemble_function`/`xrefs_to` for disputed control/data evidence.
5. Rename a function, change prototype or set comments **only** with
   sufficient target evidence and readback. Persist/cache state using
   the selected tool's actual advertised capabilities — don't assume
   a write is durable across file-close or worker restart.

## Known caller-state error is not a crash

The native engine returns MCP error `-32611` when `list_files` is used
before `open_file`; Analyzer-R preserves that caller-facing rejection
and avoids logging it as a duplicate infrastructure alarm.
This is a known sequencing error, **not** a reason to restart the
radare2 engine or reimport a second project.
See the [native provider contract](../../../services/hands/radare2/README.md)
and its source tests.

Other transport failures and engine errors remain errors. Check
which layer rejected the call: ChatGPT/Gateway → Analyzer-R proxy →
native radare2. An error in an internal proxy may not prove the
native engine is down. Do not repeatedly run heavy analysis to
clear a stale handle without checking the open-file state.

## Do not mix analyzer models

Analyzer-R uses radare2's addresses, functions, flags and decompiler
selection; Analyzer G uses project-scoped **action nodes** and a separate
persistent worker model. Do not pass Analyzer G `project_id` or action
labels to native radare2, and do not substitute radare2's temporary
open-file state for Analyzer G's saved project database.

**Acceptance:** intended file is demonstrably open, output addresses
and target identity match, analysis evidence is bounded and verified,
and no caller-state rejection was misreported as engine failure.
