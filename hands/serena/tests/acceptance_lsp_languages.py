"""Semantic TypeScript/clangd acceptance in a disposable offline image."""

import argparse
import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class SemanticFixture:
    library: str
    application: str
    original: str
    replacement: str
    body: str
    command: str | None = None


def python_fixture(project: Path) -> SemanticFixture:
    (project / "library.py").write_text(
        'class Greeter:\n    def greet(self) -> str:\n        return "hello"\n',
        encoding="utf-8",
    )
    (project / "application.py").write_text(
        "from library import Greeter\n\ndef render() -> str:\n    return Greeter().greet()\n",
        encoding="utf-8",
    )
    return descriptor("python")


async def verify_files(project: Path, fixture: SemanticFixture) -> None:
    library, application = await asyncio.gather(
        asyncio.to_thread((project / fixture.library).read_text),
        asyncio.to_thread((project / fixture.application).read_text),
    )
    assert fixture.replacement in library
    if fixture.library.endswith(".py"):
        compile(library, fixture.library, "exec")
    assert "Welcomer" in library and "Welcomer" in application
    assert "Greeter" not in application


Language = Literal["python", "typescript", "cpp"]


def parse_language(value: str) -> Language:
    match value:
        case "python":
            return "python"
        case "typescript":
            return "typescript"
        case "cpp":
            return "cpp"
        case _:
            raise ValueError("An installed fixture language is required")


def descriptor(language: Language) -> SemanticFixture:
    if language == "python":
        return SemanticFixture(
            "library.py",
            "application.py",
            "hello",
            'return "updated"',
            'def greet(self) -> str:\n        return "updated"',
            "python -c 'from application import render; print(render())'",
        )
    if language == "typescript":
        return SemanticFixture(
            "library.ts",
            "application.ts",
            "return701;",
            "return 709;",
            "greet(): number {\n    return 709;\n}",
        )
    return SemanticFixture(
        "library.hpp",
        "application.cpp",
        "return701;",
        "return 709;",
        "int greet() const {\n    return 709;\n}",
    )


def fixture(project: Path, language: Language) -> SemanticFixture:
    if language == "python":
        return python_fixture(project)
    selected = descriptor(language)
    if language == "typescript":
        (project / selected.library).write_text(
            "export class Greeter {\n  greet(): number { return 701; }\n}\n",
            encoding="utf-8",
        )
        (project / selected.application).write_text(
            "import { Greeter } from './library';\n"
            "export function render(): number { return new Greeter().greet(); }\n",
            encoding="utf-8",
        )
        (project / "tsconfig.json").write_text(
            json.dumps(
                {
                    "compilerOptions": {
                        "target": "ES2020",
                        "module": "CommonJS",
                        "strict": True,
                        "noEmit": True,
                    },
                    "include": ["*.ts"],
                }
            ),
            encoding="utf-8",
        )
    else:
        (project / selected.library).write_text(
            "#pragma once\nclass Greeter {\npublic:\n  int greet() const { return 701; }\n};\n",
            encoding="utf-8",
        )
        (project / selected.application).write_text(
            '#include "library.hpp"\nint render() { Greeter g; return g.greet(); }\n',
            encoding="utf-8",
        )
        (project / "compile_commands.json").write_text(
            json.dumps(
                [
                    {
                        "directory": str(project),
                        "file": str(project / selected.application),
                        "arguments": [
                            "clang++",
                            "-std=c++17",
                            "-I" + str(project),
                            "-c",
                            str(project / selected.application),
                        ],
                    }
                ]
            ),
            encoding="utf-8",
        )
    return selected


def owned_project(relative: str) -> Path:
    if re.fullmatch(r"\.deferred-(python|typescript|cpp)-[0-9a-f]{32}", relative) is None:
        raise ValueError("Only a generated disposable acceptance fixture is supported")
    return Path("/project-data") / relative


async def main(language: Language) -> None:
    from acceptance_deferred_lsp import main as deferred_main

    await deferred_main(language)


class Options(argparse.Namespace):
    language: str
    prepare_relative: str | None
    verify_relative: str | None


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", choices=["python", "typescript", "cpp"])
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare-relative")
    modes.add_argument("--verify-relative")
    options = Options()
    parser.parse_args(namespace=options)
    language = parse_language(options.language)
    if options.prepare_relative is not None:
        project = owned_project(options.prepare_relative)
        project.mkdir(mode=0o700)
        fixture(project, language)
    elif options.verify_relative is not None:
        project = owned_project(options.verify_relative)
        asyncio.run(verify_files(project, descriptor(language)))
        shutil.rmtree(project)
    else:
        asyncio.run(main(language))


if __name__ == "__main__":
    cli()
