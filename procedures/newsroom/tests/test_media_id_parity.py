from __future__ import annotations

import json
import unittest
from pathlib import Path

from papyrus_content.markus_import import media_id_for

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "fixtures" / "media-id-cases.json"


class MediaIdParityTests(unittest.TestCase):
    def test_importer_media_ids_match_the_shared_fixture(self) -> None:
        cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 5)
        for case in cases:
            with self.subTest(srcPath=case["srcPath"]):
                self.assertEqual(media_id_for(case["itemId"], case["srcPath"]), case["expected"])


if __name__ == "__main__":
    unittest.main()
