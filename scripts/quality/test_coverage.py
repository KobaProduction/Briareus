"""Regression tests for package roots and source accidentally hidden by directory names."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import runner
import selection


def test_regular_package_uses_parent_for_mypy(tmp_path: Path) -> None:
    package = tmp_path / "authorization"
    package.mkdir()
    (package / "__init__.py").touch()
    assert runner.python_source_root(package) == tmp_path


def test_src_layout_keeps_its_own_root(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert runner.python_source_root(tmp_path) == tmp_path / "src"


def test_ruff_receives_explicit_tracked_build_source() -> None:
    path = "shared/build/runtime_write_provenance.py"
    result = runner.Result("ruff", 0, 0, "unused")
    with patch.object(runner, "run", return_value=result) as execute:
        assert runner.python_lint([path]) == [result]
        assert path in execute.call_args.args[1]
        assert "." not in execute.call_args.args[1]


@pytest.fixture
def independent_source_owners(tmp_path: Path) -> tuple[Path, list[str]]:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.mypy]\nstrict = true\ndisallow_any_explicit = true\n", encoding="utf-8"
    )
    files = []
    for name, annotation, value in (("admin-api", "int", "1"), ("other", "str", '"other"')):
        base = tmp_path / "services" / name
        if name == "other":
            base.mkdir(parents=True)
            (base / "pyproject.toml").touch()
        for package in ("application", "domain"):
            directory = base / "src" / package
            directory.mkdir(parents=True)
            (directory / "__init__.py").touch()
        sources = (
            ("domain/value.py", f"VALUE: {annotation} = {value}\n"),
            (
                "application/service.py",
                "from domain.value import VALUE\n\n"
                f"def read() -> {annotation}:\n    return VALUE\n",
            ),
        )
        for relative, source in sources:
            target = base / "src" / relative
            target.write_text(source, encoding="utf-8")
            files.append(target.relative_to(tmp_path).as_posix())
    return tmp_path, files


def test_no_pyproject_owner_keeps_dependency_project(
    independent_source_owners: tuple[Path, list[str]],
) -> None:
    root, files = independent_source_owners
    with patch.object(selection, "ROOT", root):
        admin = files[0]
        assert selection.owner(admin) == root
        assert selection.source_owner(admin) == root / "services/admin-api"
        assert runner.python_groups([admin]) == [runner.Group(root, [admin])]
        assert runner.python_groups(files, logical_sources=True) == [
            runner.Group(root / "services/admin-api", files[:2]),
            runner.Group(root / "services/other", files[2:]),
        ]


def test_type_command_uses_logical_root_and_dependency_interpreter(
    independent_source_owners: tuple[Path, list[str]],
) -> None:
    root, files = independent_source_owners
    interpreter = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    result = runner.Result("unused", 0, 0, "unused")
    with (
        patch.object(selection, "ROOT", root),
        patch.object(runner, "ROOT", root),
        patch.object(runner, "run", return_value=result) as execute,
    ):
        runner.python_types(files[:2])
        name, command = execute.call_args.args
        assert name == "mypy-services_admin-api"
        assert command[-2:] == files[:2]
        assert command[command.index("--python") + 1] == str(interpreter)
        assert "--no-sync" in command
        assert "--no-env-file" in command
        assert "--python-executable" not in command
        assert execute.call_args.kwargs["env"]["MYPYPATH"].split(os.pathsep) == [
            str(root / "services/admin-api/src"),
            str(root / "shared"),
            str(root / "services"),
        ]


def test_type_roots_include_only_existing_reuse_packages(tmp_path: Path) -> None:
    source = tmp_path / "services" / "api" / "src"
    dependency = tmp_path / "hands" / "svc" / "src"
    dependency.mkdir(parents=True)
    with patch.object(runner, "ROOT", tmp_path):
        assert runner.python_import_roots(source) == [
            source,
            tmp_path / "shared",
            tmp_path / "services",
            dependency,
        ]


def test_root_tests_use_project_dependency_environment(
    tmp_path: Path,
) -> None:
    with patch.object(runner, "ROOT", tmp_path):
        command = runner.test_command(tmp_path)
    assert command[command.index("--project") + 1] == str(tmp_path)
    assert "--frozen" in command
    assert "--no-env-file" in command
    assert command[-4:] == ["-m", "pytest", "-q", "--import-mode=importlib"]


def test_test_environment_keeps_owner_before_bounded_consumer_paths(tmp_path: Path) -> None:
    owner = tmp_path / "services" / "authorization"
    source = owner / "src"
    consumer = tmp_path / "services" / "api" / "src"
    dependency = tmp_path / "hands" / "svc" / "src"
    foreign = tmp_path / "services" / "other" / "src"
    for path in (source, consumer, dependency, foreign):
        path.mkdir(parents=True)
    with patch.object(runner, "ROOT", tmp_path):
        environment = runner.test_environment(owner, [str(source)])
    roots = environment.values["PYTHONPATH"].split(os.pathsep)
    assert roots[0] == str(source)
    assert str(consumer) in roots
    assert str(dependency) in roots
    assert roots.index(str(dependency)) > roots.index(str(source))
    assert str(foreign) not in roots
    assert len(roots) == len(set(roots))
    assert "VIRTUAL_ENV" not in environment.values


def test_same_named_application_and_domain_packages_typecheck_separately(
    independent_source_owners: tuple[Path, list[str]],
) -> None:
    root, files = independent_source_owners
    with (
        patch.object(selection, "ROOT", root),
        patch.object(runner, "ROOT", root),
        patch.object(runner, "REPORTS", root / "reports"),
    ):
        results = runner.python_types([str(root / path) for path in files])
        assert [result.name for result in results] == [
            "mypy-services_admin-api",
            "mypy-services_other",
        ]
        assert [result.status for result in results] == [0, 0], [
            (root / result.log).read_text(encoding="utf-8") for result in results
        ]
