"""Read actual Linux placement facts without granting process authority."""

import os
from pathlib import Path

from web_hand.domain.isolation import BrowserIsolation, BrowserPrivileges


def read_browser_privileges() -> BrowserPrivileges:
    facts = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    return BrowserPrivileges(
        os.geteuid(),
        facts["NoNewPrivs"].strip() == "1",
        int(facts["CapEff"].strip(), 16),
        bool(os.statvfs("/").f_flag & os.ST_RDONLY),
        Path("/var/run/docker.sock").exists(),
        "BRIAREUS_DEPLOYMENT" in os.environ,
    )


def read_browser_isolation() -> BrowserIsolation:
    privileges = read_browser_privileges()
    return BrowserIsolation(
        privileges.uid,
        privileges.no_new_privileges,
        privileges.capabilities,
        privileges.readonly_root,
        privileges.docker_socket,
        privileges.deployment_present,
        frozenset(item.name for item in Path("/sys/class/net").iterdir()),
    )
