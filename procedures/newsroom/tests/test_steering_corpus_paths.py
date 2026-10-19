from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.steering import resolve_corpus_local_path  # noqa: E402


class SteeringCorpusPathTests(unittest.TestCase):
    def test_resolve_corpus_local_path_uses_steering_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            steering_path = root / "corpora" / "papyrus-steering.yml"
            steering_path.parent.mkdir(parents=True, exist_ok=True)
            corpus_dir = root / "corpora" / "demo-corpus"
            corpus_dir.mkdir(parents=True)
            (corpus_dir / "metadata").mkdir()
            (corpus_dir / "metadata" / "catalog.json").write_text('{"items": {}}', encoding="utf-8")
            steering_config = {"configPath": str(steering_path)}
            corpus = {"key": "demo-corpus", "path": "corpora/demo-corpus"}
            resolved = resolve_corpus_local_path(corpus, steering_config)
            self.assertEqual(resolved, corpus_dir.resolve())


if __name__ == "__main__":
    unittest.main()
