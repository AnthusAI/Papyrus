from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.editorial_commands import editorial_diagnose  # noqa: E402


class EditorialCommandsLimatusTests(unittest.TestCase):
    def test_editorial_diagnose_calls_limatus_diagnose(self) -> None:
        profile = (
            REPO_ROOT
            / "features_backend"
            / "fixtures"
            / "editorial-diagnosis"
            / "style-profile.yml"
        )
        minimal_diagnosis = {
            "schemaVersion": 1,
            "density": {
                "wordCount": 1,
                "lexicalDensity": 0.5,
                "gzipRatio": 0.2,
            },
            "generic_passages": [],
            "voice_mismatches": [],
            "vague_claims": [],
            "empty_leadins": [],
            "unsupported_certainties": [],
            "uniform_cadence": [],
            "redundancy": [],
            "repetition_groups": [],
            "missing_attribution": [],
        }
        config = object()
        with mock.patch(
            "papyrus_content.editorial_commands.load_config",
            return_value=config,
        ) as load_config:
            with mock.patch(
                "papyrus_content.editorial_commands.diagnose",
                return_value=minimal_diagnosis,
            ) as diagnose:
                editorial_diagnose(
                    [
                        "--text",
                        "Hello world.",
                        "--profile",
                        str(profile),
                    ]
                )
                load_config.assert_called_once()
                diagnose.assert_called_once_with("Hello world.", config=config)
