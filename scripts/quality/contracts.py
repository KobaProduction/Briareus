"""Check typed result contracts and real cognitive complexity, without executing source."""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass

from complexipy import file_complexity
from selection import ROOT, is_test

DICTIONARIES = {"dict", "Dict", "Mapping", "MutableMapping", "defaultdict", "OrderedDict"}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    code: str
    message: str


def name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else ""


def names_in(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return names_in(ast.parse(node.value, mode="eval").body)
        except SyntaxError:
            return set()
    return {name(child) for child in ast.walk(node)} - {""}


def assignment_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Assign):
        return {target.id for target in node.targets if isinstance(target, ast.Name)}
    if isinstance(node, (ast.AnnAssign, ast.TypeAlias)):
        target = node.target if isinstance(node, ast.AnnAssign) else node.name
        return {target.id} if isinstance(target, ast.Name) else set()
    return set()


def dictionary_alias(value: ast.AST, aliases: set[str]) -> bool:
    type_expression = isinstance(
        value, (ast.Name, ast.Attribute, ast.Subscript, ast.BinOp, ast.Constant)
    )
    return (type_expression and bool(names_in(value) & aliases)) or is_dictionary(value, aliases)


def dictionary_names(tree: ast.Module) -> set[str]:
    result = set(DICTIONARIES)
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    for imported in imports:
        result.update(
            alias.asname or alias.name for alias in imported.names if alias.name in result
        )
    previous: set[str] = set()
    while previous != result:
        previous = result.copy()
        for node in tree.body:
            value = getattr(node, "value", None)
            if isinstance(value, ast.AST) and dictionary_alias(value, result):
                result.update(assignment_names(node))
    return result


def is_dictionary(node: ast.AST, aliases: set[str]) -> bool:
    if isinstance(node, (ast.Dict, ast.DictComp)):
        return True
    if isinstance(node, ast.Call):
        return name(node.func) in aliases
    if isinstance(node, ast.IfExp):
        return is_dictionary(node.body, aliases) or is_dictionary(node.orelse, aliases)
    return isinstance(node, ast.Name) and node.id in aliases


def function_nodes(function: ast.AST) -> Iterable[ast.AST]:
    for child in ast.iter_child_nodes(function):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield child
        yield from function_nodes(child)


def dictionary_variables(nodes: list[ast.AST], aliases: set[str]) -> set[str]:
    variables = set(aliases)
    previous: set[str] = set()
    while previous != variables:
        previous = variables.copy()
        for node in nodes:
            value = getattr(node, "value", None)
            if isinstance(value, ast.AST) and is_dictionary(value, variables):
                variables.update(assignment_names(node))
    return variables


def dictionary_parameters(function: ast.AST, aliases: set[str]) -> set[str]:
    if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set()
    args = function.args
    parameters = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    names = {
        arg.arg
        for arg in parameters
        if arg.annotation is not None and bool(names_in(arg.annotation) & aliases)
    }
    if args.kwarg is not None:
        names.add(args.kwarg.arg)
    return names


def returned_dictionary(function: ast.AST, aliases: set[str]) -> bool:
    nodes = list(function_nodes(function))
    variables = dictionary_variables(nodes, aliases | dictionary_parameters(function, aliases))
    return any(
        isinstance(n, ast.Return) and n.value is not None and is_dictionary(n.value, variables)
        for n in nodes
    )


def contract_findings(path: str) -> list[Finding]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"), filename=path)
    aliases = dictionary_names(tree)
    findings: list[Finding] = []
    for function in ast.walk(tree):
        if isinstance(function, ast.Lambda) and is_dictionary(function.body, aliases):
            findings.append(
                Finding(path, function.lineno, "BRI001", "Lambda returns a dictionary.")
            )
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        annotation = function.returns
        if (annotation is not None and names_in(annotation) & aliases) or returned_dictionary(
            function, aliases
        ):
            findings.append(
                Finding(
                    path,
                    function.lineno,
                    "BRI001",
                    "Return a structured result (dataclass, NamedTuple or model), "
                    "not a dictionary.",
                )
            )
    return findings


def complexity_findings(path: str) -> list[Finding]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["briareus-quality"]
    limit = config["cognitive-tests" if is_test(path) else "cognitive-production"]
    result = file_complexity(str(ROOT / path), no_ignore=True)
    return [
        Finding(
            path, f.line_start, "COG001", f"{f.name}: cognitive complexity {f.complexity} > {limit}"
        )
        for f in result.functions
        if f.complexity > limit
    ]


def check(paths: list[str]) -> int:
    findings: list[Finding] = []
    for path in paths:
        try:
            findings.extend(contract_findings(path))
            findings.extend(complexity_findings(path))
        except (SyntaxError, ValueError) as error:
            findings.append(Finding(path, 1, "PARSE001", str(error)))
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.code} {finding.message}")
    return int(bool(findings))
