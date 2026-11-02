"""Offline watch safety, consumer ordering and CLI wire compatibility."""

import json
from pathlib import Path

import pytest
import watch_impact
from watch_policy import ImpactError, WatchPattern, WatchPlan, calculate_impact
from watch_sources import WatchSource, parse_watch_plan


@pytest.mark.parametrize("pattern", ["", "/absolute", "!excluded", "services/../private"])
def test_rejects_unsafe_native_watch_patterns(pattern: str) -> None:
    with pytest.raises(ImpactError, match="unsafe watch path"):
        parse_watch_plan("gateway", "x-watch-path-coolify:\n  - " + json.dumps(pattern))


def test_directory_watch_is_bounded_by_path_separator() -> None:
    pattern = WatchPattern("services/external/**")
    assert pattern.matches("services/external/config/owner-databases.json")
    assert not pattern.matches("services/external-old/config.json")
    assert not pattern.matches("services/external")


def test_native_watch_source_rejects_empty_duplicate_and_non_string_items() -> None:
    for source in (
        "x-watch-path-coolify:\nservices: {}",
        'x-watch-path-coolify:\n  - "shared/**"\n  - "shared/**"',
        'x-watch-path-coolify:\n  - {"unexpected": "value"}',
    ):
        with pytest.raises(ImpactError):
            parse_watch_plan("gateway", source)


def test_impact_is_immutable_and_preserves_registry_and_first_seen_path_order() -> None:
    shared = WatchPattern("services/external/**")
    plans = (
        WatchPlan("resources", (shared, WatchPattern("services/resources/**"))),
        WatchPlan("gateway", (shared,)),
    )
    external = "services/external/config.json"
    own = "services/resources/catalog.py"
    result = calculate_impact(plans, [external, own, external, "docs/readme.md"])
    assert [entry.path for entry in result.files] == [external, own, "docs/readme.md"]
    assert result.consumers(external) == ("resources", "gateway")
    assert result.consumers(own) == ("resources",)
    assert result.consumers("docs/readme.md") == ()
    with pytest.raises(KeyError):
        result.consumers("unrequested")


def _source(tmp_path: Path) -> WatchSource:
    deployment = tmp_path / "deploy"
    deployment.mkdir()
    (deployment / "APPLICATIONS.json").write_text(
        json.dumps({"applications": [{"module": "resources"}, {"module": "gateway"}]})
    )
    for module, parent in (("resources", tmp_path / "services"), ("gateway", deployment)):
        folder = parent / module
        folder.mkdir(parents=True)
        (folder / "docker-compose.coolify.yaml").write_text(
            'x-watch-path-coolify:\n  - "services/external/**"\nservices: {}\n'
        )
    return WatchSource(deployment, tmp_path)


def test_source_adapter_uses_canonical_owner_folder_and_cli_keeps_wire_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    monkeypatch.setattr(watch_impact, "ROOT", source.deployment)
    monkeypatch.setattr(watch_impact, "REPO", source.repository)
    monkeypatch.setattr("sys.argv", ["watch_impact.py", "--changed-file", "services/external/x"])
    assert watch_impact.main() == 0
    assert json.loads(capsys.readouterr().out) == {"services/external/x": ["resources", "gateway"]}


def test_pending_migrations_remain_explicit_and_other_missing_sources_fail(tmp_path: Path) -> None:
    source = _source(tmp_path)
    pending = watch_impact._watch_exists(source, "resources", "scripts/alembic_owners/x/**", True)
    assert pending == "resources: scripts/alembic_owners/x/** (A11 NOT FAN-IN)"
    with pytest.raises(ImpactError, match="nonexistent directory"):
        watch_impact._watch_exists(source, "resources", "services/missing/**", True)
    with pytest.raises(ImpactError, match="nonexistent directory"):
        watch_impact._watch_exists(source, "resources", "scripts/alembic_owners/x/**", False)
