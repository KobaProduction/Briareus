"""Fixed sandbox profile changes namespace/chroot/openat2 syscall admission only."""

import hashlib
import json
import unittest
from pathlib import Path

from node_agent import browser_seccomp
from node_agent.infrastructure.seccomp_profiles import (
    BrowserSeccompProfile,
    SeccompConditions,
    SeccompRule,
)


class BrowserSeccompTests(unittest.TestCase):
    def test_pinned_default_deny_and_only_reviewed_delta(self) -> None:
        raw = browser_seccomp._PROFILE.encode()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), browser_seccomp.SOURCE_SHA256)
        upstream = BrowserSeccompProfile.model_validate_json(raw)
        effective = browser_seccomp.browser_seccomp_profile()
        self.assertEqual(effective.default_action, "SCMP_ACT_ERRNO")
        self.assertEqual(effective.syscalls[2:], upstream.syscalls)
        self.assertEqual(effective.syscalls[0].names, ["chroot", "openat2"])
        self.assertEqual(
            effective.syscalls[1],
            SeccompRule(
                names=["clone3"],
                action="SCMP_ACT_ERRNO",
                errno_ret=38,
                excludes=SeccompConditions(caps=["CAP_SYS_ADMIN"]),
            ),
        )
        namespace = [
            rule for rule in effective.syscalls if rule.names == ["clone", "setns", "unshare"]
        ]
        self.assertEqual(len(namespace), 1)
        self.assertEqual(namespace[0].action, "SCMP_ACT_ALLOW")
        wire = json.loads(browser_seccomp.browser_seccomp_security_option().split("=", 1)[1])
        self.assertEqual(wire, effective.model_dump(mode="json", by_alias=True, exclude_unset=True))

    def test_cli_fixture_profile_matches_embedded_runtime_profile(self) -> None:
        profile = Path(__file__).resolve().parents[1] / "security" / "browser-seccomp.json"
        self.assertEqual(
            BrowserSeccompProfile.model_validate_json(profile.read_text()),
            browser_seccomp.browser_seccomp_profile(),
        )


if __name__ == "__main__":
    unittest.main()
