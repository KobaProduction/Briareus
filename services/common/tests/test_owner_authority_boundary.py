"""Owner phase lookup must not require SQL/JWT/framework dependencies in a Hand."""

import subprocess
import sys
import unittest
from pathlib import Path

from common import owner_effect_phase_map
from common.domain.owner_authority import OWNER_DB_NAMES, OwnerAuthorityUnavailable


class OwnerAuthorityBoundaryTests(unittest.TestCase):
    def test_phase_rejection_preserves_exception_identity(self) -> None:
        with self.assertRaises(OwnerAuthorityUnavailable):
            owner_effect_phase_map.require_exact_owner_operation(
                owner="files", phase="unknown", payload_type="unknown", operation="unknown"
            )
        self.assertEqual(OWNER_DB_NAMES["resources"], "briareus_resources")
        self.assertEqual(len(OWNER_DB_NAMES), 8)

    def test_phase_import_has_no_site_package_or_persistence_requirement(self) -> None:
        subprocess.run(  # noqa: S603 -- fixed interpreter/argv/code; source path is a data argument
            [
                sys.executable,
                "-I",
                "-S",
                "-c",
                "import sys; sys.path[:0] = sys.argv[1:]; "
                "import common.owner_effect_phase_map; "
                "assert 'common.platform_db' not in sys.modules; "
                "assert 'sqlalchemy' not in sys.modules; "
                "assert 'jwt' not in sys.modules; assert 'pydantic' not in sys.modules",
                str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parents[3] / "shared"),
            ],
            check=True,
            timeout=5,
        )
