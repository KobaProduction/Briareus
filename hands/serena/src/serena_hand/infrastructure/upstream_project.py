"""Provider-owned project configuration runs in the pinned upstream environment."""

import importlib.metadata
import sys
from pathlib import Path

from serena.config.serena_config import ProjectConfig, SerenaConfig
from solidlsp.ls_config import LanguageServerId

from serena_hand.confinement import project_root
from serena_hand.domain.languages import SourceLanguage
from serena_hand.runtime import UPSTREAM_VERSION


def main() -> None:
    if importlib.metadata.version("serena-agent") != UPSTREAM_VERSION:
        raise ValueError("Exact pinned upstream Serena is required")
    requested = Path(sys.argv[1])
    relative = requested.relative_to("/project-data")
    project = project_root(str(relative))
    selected = tuple(SourceLanguage[name] for name in sys.argv[2:])
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Distinct detected source languages required")
    ProjectConfig.autogenerate(
        project,
        SerenaConfig.from_config_file(),
        project_name="Briareus project",
        languages=[LanguageServerId[language.name] for language in selected],
        interactive=False,
        asynchronous=False,
    )


if __name__ == "__main__":
    main()
