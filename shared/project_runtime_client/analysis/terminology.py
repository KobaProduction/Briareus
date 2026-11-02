from __future__ import annotations

import re

from service_runtime.public_tool_names import analysis_public_tool_name

from .catalog_views import AnalysisVocabulary

_ARGUMENT_ALIASES: dict[str, str] = {
    "function": "action",
    "function_name": "action_name",
    "function_address": "action_address",
    "function_names": "action_names",
    "start_function": "start_action",
    "end_function": "end_action",
    "source_function": "source_action",
    "target_function": "target_action",
    "caller": "inbound_action",
    "callers": "inbound_actions",
    "callee": "outbound_action",
    "callees": "outbound_actions",
    "include_callers": "include_inbound_actions",
    "include_callees": "include_outbound_actions",
    "include_disasm": "include_low_level_view",
    "decompiler_comments": "behavior_annotations",
    "disassembly_comments": "low_level_annotations",
    "disassemble_first": "analyze_low_level_first",
    "include_assembly_patterns": "include_low_level_patterns",
    "context_instructions": "context_operations",
    "gzf_path": "package_path",
    "gar_path": "archive_path",
}

_TOOL_ARGUMENT_ALIASES: dict[str, dict[str, str]] = {
    "get_function_callees": {"name": "action"},
    "get_function_callers": {"name": "action"},
    "get_function_call_graph": {"name": "action"},
    "get_function_xrefs": {"name": "action"},
    "analyze_function_complete": {"name": "action"},
    "decompile_function": {"address": "action", "functions": "actions"},
    "disassemble_function": {"address": "action"},
    "get_function_by_address": {"address": "action"},
    "audit_globals_in_function": {"address": "action"},
    "force_decompile": {"address": "action"},
    "get_comment": {"address": "action"},
    "disassemble_bytes": {
        "include_instructions": "include_low_level_operations",
    },
}

_COLLAPSED_ACTION_SELECTOR_TOOLS = frozenset(
    {
        "get_function_callees",
        "get_function_callers",
        "get_function_call_graph",
        "get_function_xrefs",
    }
)

_ARGUMENT_TOKENS: dict[str, str] = {
    "ghidra": "analysis",
    "binary": "program",
    "memory": "data",
    "assembly": "low_level",
    "disassembly": "low_level_view",
    "disassemble": "analyze_low_level",
    "decompiler": "behavior",
    "decompile": "behavior",
    "pcode": "ir",
    "opcode": "operation",
    "malware": "behavior",
    "instructions": "operations",
    "instruction": "operation",
    "functions": "actions",
    "function": "action",
    "xrefs": "links",
    "xref": "link",
    "thunks": "forwarders",
    "thunk": "forwarder",
}

_TOOL_TOKENS: dict[str, str] = {
    "ghidra": "analysis",
    "decompile": "inspect",
    "decompiler": "behavior",
    "disassemble": "analyze",
    "disassembly": "low_level",
    "assembly": "low_level",
    "pcode": "ir",
    "opcode": "operation",
    "malware": "behavior",
    "binary": "program",
    "memory": "data",
    "instructions": "operations",
    "instruction": "operation",
    "functions": "actions",
    "function": "action",
    "callers": "inbound_actions",
    "caller": "inbound_action",
    "callees": "outbound_actions",
    "callee": "outbound_action",
    "xrefs": "links",
    "xref": "link",
}

_GROUP_ALIASES: dict[str, str] = {
    "function": "actions",
    "xref": "links",
    "malware": "behavior patterns",
    "headless": "project runtime",
    "server": "repository",
    "getter": "context",
    "comment": "annotations",
}


_TEXT_TERMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"re_kb\.action nodes on bsim Postgres", re.IGNORECASE),
        "analysis records in archive storage",
    ),
    (
        re.compile(r"DAT_\*-style autogen", re.IGNORECASE),
        "auto-generated placeholders",
    ),
    (re.compile(r"FUN_\*", re.IGNORECASE), "default-named"),
    (re.compile(r"\bxrefed\b", re.IGNORECASE), "linked"),
    (re.compile(r"\bDomainFile\b", re.IGNORECASE), "project file"),
    (
        re.compile(r"\bClearFlowAndRepairCmd\b", re.IGNORECASE),
        "runtime repair command",
    ),
    (re.compile(r"\bSwing thread\b", re.IGNORECASE), "runtime command thread"),
    (re.compile(r"\bJava source\b", re.IGNORECASE), "source code"),
    (re.compile(r"\bheadless\b", re.IGNORECASE), "isolated"),
    (re.compile(r"\bBSim\b", re.IGNORECASE), "archive storage"),
    (re.compile(r"\bbatch_remove_function_tags\b", re.IGNORECASE), "remove_action_tag"),
    (re.compile(r"\bthunks\b", re.IGNORECASE), "forwarders"),
    (re.compile(r"\bthunk\b", re.IGNORECASE), "forwarder"),
    (re.compile(r"\bfunction_address\b", re.IGNORECASE), "action_address"),
    (re.compile(r"\bRE documentation\b", re.IGNORECASE), "analysis documentation"),
    (re.compile(r"add_function_tag", re.IGNORECASE), "add_action_tag"),
    (re.compile(r"delete_function_tag", re.IGNORECASE), "delete_action_tag"),
    (
        re.compile(r"analyze_function_completeness", re.IGNORECASE),
        "measure_action_documentation",
    ),
    (re.compile(r"rename_function", re.IGNORECASE), "set_action_name"),
    (re.compile(r"set_function_this_type", re.IGNORECASE), "set_action_this_type"),
    (re.compile(r"add_memory_reference", re.IGNORECASE), "add_data_relationship"),
    (
        re.compile(r"GHIDRA_MCP_ALLOW_SCRIPTS", re.IGNORECASE),
        "analysis scripting setting",
    ),
    (
        re.compile(r"GhidraServerManager", re.IGNORECASE),
        "repository manager",
    ),
    (
        re.compile(r"set_decompiler_variable_type", re.IGNORECASE),
        "set_behavior_variable_type",
    ),
    (
        re.compile(r"set_decompiler_comment", re.IGNORECASE),
        "set_behavior_annotation",
    ),
    (
        re.compile(r"set_disassembly_comment", re.IGNORECASE),
        "set_low_level_annotation",
    ),
    (re.compile(r"\bGhidra Server\b", re.IGNORECASE), "repository service"),
    (re.compile(r"\bGhidra GUI\b", re.IGNORECASE), "desktop analysis client"),
    (re.compile(r"\bGhidra-native\b", re.IGNORECASE), "native analysis"),
    (re.compile(r"\bGhidra projects?\b", re.IGNORECASE), "analysis projects"),
    (re.compile(r"\bGhidra tools?\b", re.IGNORECASE), "analysis tools"),
    (re.compile(r"\bGhidra's\b", re.IGNORECASE), "analysis runtime's"),
    (re.compile(r"\bGhidra(?:MCP)?\b", re.IGNORECASE), "analysis runtime"),
    (re.compile(r"\bTraceRmi\b", re.IGNORECASE), "runtime trace interface"),
    (re.compile(r"\bdbgeng\b", re.IGNORECASE), "runtime debug engine"),
    (re.compile(r"\bWinDbg\b", re.IGNORECASE), "runtime debugger"),
    (re.compile(r"\bJython\b", re.IGNORECASE), "scripting runtime"),
    (re.compile(r"\breverse engineering\b", re.IGNORECASE), "behavior analysis"),
    (re.compile(r"\bauto-analysis\b", re.IGNORECASE), "behavior analysis"),
    (re.compile(r"\breversing\b", re.IGNORECASE), "behavior recovery"),
    (re.compile(r"\bcross[- ]binary\b", re.IGNORECASE), "cross-program"),
    (re.compile(r"\bbinary files?\b", re.IGNORECASE), "program files"),
    (re.compile(r"\bbinary versions?\b", re.IGNORECASE), "program versions"),
    (re.compile(r"\bbinaries\b", re.IGNORECASE), "programs"),
    (re.compile(r"\bbinary\b", re.IGNORECASE), "program"),
    (re.compile(r"\bP[- ]?code\b", re.IGNORECASE), "intermediate representation"),
    (re.compile(r"\bHighFunction\b", re.IGNORECASE), "high-level behavior graph"),
    (re.compile(r"\bvarnodes?\b", re.IGNORECASE), "value nodes"),
    (re.compile(r"\bopcode\b", re.IGNORECASE), "operation"),
    (re.compile(r"\bmalware behaviors?\b", re.IGNORECASE), "behavior patterns"),
    (re.compile(r"\bmalware\b", re.IGNORECASE), "behavior"),
    (re.compile(r"\bdecompiler's\b", re.IGNORECASE), "behavior engine's"),
    (re.compile(r"\bdecompilers\b", re.IGNORECASE), "behavior engines"),
    (re.compile(r"\bdecompiler\b", re.IGNORECASE), "behavior engine"),
    (re.compile(r"\bdecompilation\b", re.IGNORECASE), "behavior inspection"),
    (re.compile(r"\bdecompiled\b", re.IGNORECASE), "behavior view"),
    (re.compile(r"\bdecompile\b", re.IGNORECASE), "inspect behavior"),
    (re.compile(r"\bdisasm\b", re.IGNORECASE), "low-level view"),
    (
        re.compile(r"\bre-disassembl(?:e|es|ed|y)\b", re.IGNORECASE),
        "re-analyze low-level operations",
    ),
    (re.compile(r"\bdisassembled\b", re.IGNORECASE), "decoded low-level"),
    (re.compile(r"\bdisassemble\b", re.IGNORECASE), "analyze low-level operations"),
    (re.compile(r"\bdisassembly\b", re.IGNORECASE), "low-level action view"),
    (re.compile(r"\bassembly\b", re.IGNORECASE), "low-level operations"),
    (re.compile(r"\bmemory\b", re.IGNORECASE), "data space"),
    (re.compile(r"\binstructions\b", re.IGNORECASE), "low-level operations"),
    (re.compile(r"\binstruction\b", re.IGNORECASE), "low-level operation"),
    (re.compile(r"\bcall graph\b", re.IGNORECASE), "link map"),
    (re.compile(r"\bcross[- ]references?\b", re.IGNORECASE), "links"),
    (re.compile(r"\bxrefs?\b", re.IGNORECASE), "links"),
    (re.compile(r"\bcallers\b", re.IGNORECASE), "inbound actions"),
    (re.compile(r"\bcaller\b", re.IGNORECASE), "inbound action"),
    (re.compile(r"\bcallees\b", re.IGNORECASE), "outbound actions"),
    (re.compile(r"\bcallee\b", re.IGNORECASE), "outbound action"),
    (re.compile(r"\bfunctions\b", re.IGNORECASE), "action nodes"),
    (re.compile(r"\bfunction\b", re.IGNORECASE), "action node"),
    (re.compile(r"\.gzf\b", re.IGNORECASE), " program package"),
    (re.compile(r"\bGZF\b", re.IGNORECASE), "program package"),
    (re.compile(r"\.gar\b", re.IGNORECASE), " project archive"),
)

_FORBIDDEN_ANALYSIS_TERMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ghidra", re.IGNORECASE),
    re.compile(r"\breverse(?:\s+engineering)?\b", re.IGNORECASE),
    re.compile(r"decomp", re.IGNORECASE),
    re.compile(r"disasm", re.IGNORECASE),
    re.compile(r"\bassembly\b", re.IGNORECASE),
    re.compile(r"\bp[- ]?code\b", re.IGNORECASE),
    re.compile(r"\bopcode\b", re.IGNORECASE),
    re.compile(r"\bmalware\b", re.IGNORECASE),
    re.compile(r"\bTraceRmi\b", re.IGNORECASE),
    re.compile(r"\bdbgeng\b", re.IGNORECASE),
    re.compile(r"\bWinDbg\b", re.IGNORECASE),
    re.compile(r"\bJython\b", re.IGNORECASE),
    re.compile(r"\bmemory\b", re.IGNORECASE),
    re.compile(r"\binstructions?\b", re.IGNORECASE),
    re.compile(
        r"(?<![A-Za-z0-9])functions?(?:_|(?![A-Za-z0-9]))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<![A-Za-z0-9])xrefs?(?:_|(?![A-Za-z0-9]))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<![A-Za-z0-9])thunks?(?:_|(?![A-Za-z0-9]))",
        re.IGNORECASE,
    ),
    re.compile(r"\bxrefed\b", re.IGNORECASE),
    re.compile(r"\bheadless\b", re.IGNORECASE),
    re.compile(r"\bBSim\b", re.IGNORECASE),
    re.compile(r"\bDomainFile\b", re.IGNORECASE),
    re.compile(r"\bClearFlowAndRepairCmd\b", re.IGNORECASE),
    re.compile(r"\bSwing\b", re.IGNORECASE),
    re.compile(r"\bJava source\b", re.IGNORECASE),
    re.compile(r"FUN_\*", re.IGNORECASE),
    re.compile(r"DAT_\*", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])gzf_path(?![A-Za-z0-9])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])gar_path(?![A-Za-z0-9])", re.IGNORECASE),
)

_RESULT_KEY_ALIASES: dict[str, str] = {
    "function": "action",
    "functions": "actions",
    "function_name": "action_name",
    "function_address": "action_address",
    "caller": "inbound_action",
    "callers": "inbound_actions",
    "callee": "outbound_action",
    "callees": "outbound_actions",
    "xrefs": "links",
    "xref_count": "link_count",
    "cross_references": "links",
    "cross_reference": "link",
    "decompiled": "behavior",
    "decompiled_code": "behavior",
    "disassembly": "low_level_view",
    "instructions": "low_level_operations",
    "instruction": "operation",
    "isThunk": "is_forwarder",
    "isExternal": "is_external",
    "pcode": "ir",
    "high_pcode": "high_ir",
    "low_pcode": "low_ir",
    "opcode": "operation",
    "ghidra_version": "runtime_version",
}

_RESULT_METADATA_KEYS = frozenset(
    {
        "error",
        "message",
        "warning",
        "warnings",
        "note",
        "notes",
        "suggestion",
        "suggestions",
        "status",
        "classification",
        "reason",
        "details",
        "diagnostic",
        "diagnostics",
    }
)

_RESULT_OPAQUE_KEYS = frozenset(
    {
        "behavior",
        "code",
        "source",
        "bytes",
        "data",
        "data_base64",
        "value",
        "comment",
        "plate",
        "pre",
        "eol",
        "post",
        "repeatable",
        "path",
        "file_path",
        "executable_path",
        "output",
        "stdout",
        "stderr",
    }
)


ANALYSIS_VOCABULARY = AnalysisVocabulary(
    action="A named behavior unit that can be addressed and inspected.",
    actions="A collection of behavior units.",
    inbound_action="An action that links into the selected action.",
    outbound_action="An action reached from the selected action.",
    link="A relationship between locations, data, or actions.",
    link_map="A graph of inbound and outbound action relationships.",
    behavior="A high-level behavioral representation of an action.",
    low_level_view="An ordered view of low-level operations for an action or data region.",
    low_level_operation="One decoded operation in a low-level view.",
    ir="An intermediate representation used for value-flow and behavior inspection.",
    program="A loaded analysis target within a project.",
    project="A persistent analysis workspace containing programs and metadata.",
    data_region="A bounded region of program data addressed within a program.",
    data_link="A relationship between data locations.",
    action_route="A connected path through action links and transitions.",
    annotation="A semantic note attached to an action, operation, or data location.",
    data_space="A named address space used by a program.",
    forwarder="A small action whose primary behavior is forwarding control to another action.",
    behavior_annotation="A semantic annotation attached to a behavior view.",
    low_level_annotation="An annotation attached to a low-level operation view.",
)


def analysis_vocabulary() -> AnalysisVocabulary:
    return ANALYSIS_VOCABULARY


def analysis_argument_name(
    ghidra_name: str,
    explicit_alias: str | None = None,
    tool_name: str | None = None,
) -> str:
    if explicit_alias is not None and explicit_alias.strip():
        return explicit_alias.strip()
    if tool_name is not None:
        tool_alias = _TOOL_ARGUMENT_ALIASES.get(tool_name, {}).get(ghidra_name)
        if tool_alias is not None:
            return tool_alias
    direct = _ARGUMENT_ALIASES.get(ghidra_name)
    if direct is not None:
        return direct
    parts = ghidra_name.split("_")
    translated = [_ARGUMENT_TOKENS.get(part, part) for part in parts]
    return "_".join(translated)


def analysis_tool_name(ghidra_name: str) -> str:
    return analysis_public_tool_name(ghidra_name)


def analysis_group_name(group_name: str) -> str:
    direct = _GROUP_ALIASES.get(group_name.strip().casefold())
    return direct if direct is not None else analysis_text(group_name)


def analysis_text(text: str) -> str:
    value = text
    for pattern, replacement in _TEXT_TERMS:
        value = pattern.sub(replacement, value)
    return value


def analysis_result_key(key: str) -> str:
    direct = _RESULT_KEY_ALIASES.get(key)
    if direct is not None:
        return direct
    parts = key.split("_")
    translated = [_TOOL_TOKENS.get(part, part) for part in parts]
    return "_".join(translated)


def analysis_result_text(text: str, key: str | None = None) -> str:
    if key in _RESULT_OPAQUE_KEYS:
        return text
    if key == "classification" and text.casefold() == "thunk":
        return "forwarder"
    metadata_suffixes = (
        "_error",
        "_message",
        "_warning",
        "_note",
        "_suggestion",
        "_diagnostic",
    )
    if key is None or key in _RESULT_METADATA_KEYS or key.endswith(metadata_suffixes):
        return analysis_text(text)
    return text


def analysis_surface_violations(text: str) -> list[str]:
    return sorted(
        {
            match.group(0)
            for pattern in _FORBIDDEN_ANALYSIS_TERMS
            for match in pattern.finditer(text)
        },
        key=str.casefold,
    )
