import filecmp
import hashlib
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.markus_export import export_content  # noqa: E402
from papyrus_content.markus_renderer.build import build_markus_site  # noqa: E402
from papyrus_content.markus_renderer.citations import CitationRendering  # noqa: E402
from papyrus_content.markus_renderer.images import ImagePipeline  # noqa: E402
from papyrus_content.markus_renderer.content_markup import split_front_matter  # noqa: E402
from papyrus_content.media_store import DirMediaStore  # noqa: E402
from papyrus_content.publishing import ItemFields, item_id_for, publish_item, save_item  # noqa: E402
from papyrus_content.record_helpers import slugify, to_aws_json  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "markus-content"
READER_OWNED = ("assets/site.js",)
NOW = "2026-10-05T12:00:00Z"
IMPORTER_AVAILABLE = importlib.util.find_spec("papyrus_content.markus_import") is not None


def stand_in_import(content_dir: Path, client, store: DirMediaStore) -> None:
    """Minimal importer built on save_item/publish_item, independent of PPY-22a3b4."""
    for path in sorted(content_dir.rglob("*.md")):
        relative = path.relative_to(content_dir)
        if relative.parts[0] in ("assets", "drafts"):
            continue
        yaml_chunk, body = split_front_matter(path.read_text(encoding="utf-8"))
        section = relative.parts[0] if len(relative.parts) > 1 else None
        slug = slugify(path.stem)
        fields = ItemFields(
            type="article" if section == "articles" else "page",
            slug=slug,
            section=section,
            front_matter_yaml=yaml_chunk.lstrip("\n"),
            body_markus=body,
            aliases=[],
            id=item_id_for(section, slug),
            source_path=relative.as_posix(),
        )
        save_item(client, fields, actor="test", now=NOW)
        if slug == "hello":
            image = content_dir / "assets" / "hello" / "a.png"
            sha = hashlib.sha256(image.read_bytes()).hexdigest()
            storage_path = "media/assets/hello/a.png"
            store.put(storage_path, image, content_type="image/png", sha256=sha)
            client.upsert(
                "MediaAsset",
                {
                    "id": "media-hello",
                    "itemId": fields.id,
                    "type": "image",
                    "role": "body",
                    "sortKey": "000#assets/hello/a.png",
                    "storagePath": storage_path,
                    "metadata": to_aws_json({"srcPath": "assets/hello/a.png", "sha256": sha}),
                },
            )
        publish_item(client, fields.id, actor="test", now=NOW)


def tree_files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def compare_trees(left: Path, right: Path, ignore=()) -> list[str]:
    differences = []
    names = {n for n in tree_files(left) | tree_files(right) if not n.startswith(tuple(ignore))}
    for name in sorted(names):
        a, b = left / name, right / name
        if not a.is_file() or not b.is_file():
            differences.append(f"only in one tree: {name}")
        elif not filecmp.cmp(a, b, shallow=False):
            differences.append(f"differs: {name}")
    return differences


class RoundTripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def import_then_export(self, importer) -> Path:
        client = FakeAuthoringClient()
        store = DirMediaStore(self.root / "bucket")
        importer(FIXTURE, client, store)
        exported = self.root / "exported"
        export_content(client, store, exported, drafts=False, now=NOW)
        return exported

    def check(self, importer):
        exported = self.import_then_export(importer)
        self.assertEqual(compare_trees(FIXTURE, exported, ignore=("drafts/", "assets/site.js", "_papyrus/")), [])
        original = self.root / "original"
        shutil.copytree(FIXTURE, original)
        shutil.rmtree(original / "drafts")
        for relative in READER_OWNED:
            (exported / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(FIXTURE / relative, exported / relative)
        executable = shutil.which("markus")
        if executable is None:
            self.skipTest("markus executable not found")
        out_original, out_exported = self.root / "dist-original", self.root / "dist-exported"
        build_markus_site(content_dir=original, out_dir=out_original, theme="hackerman", markus_executable=executable, images=ImagePipeline(), citations=CitationRendering())
        build_markus_site(content_dir=exported, out_dir=out_exported, theme="hackerman", markus_executable=executable, images=ImagePipeline(), citations=CitationRendering())
        self.assertEqual(compare_trees(out_original, out_exported), [])

    @unittest.skipUnless(shutil.which("markus"), "markus 0.5.1 executable required")
    def test_stand_in_import_export_is_byte_identical_and_builds_identical_html(self):
        self.check(stand_in_import)

    @unittest.skipUnless(IMPORTER_AVAILABLE, "PPY-22a3b4 (papyrus_content.markus_import) has not landed; remove this skip when it merges")
    @unittest.skipUnless(shutil.which("markus"), "markus 0.5.1 executable required")
    def test_markus_importer_round_trip(self):
        from papyrus_content.markus_import import ImportOptions, plan_import, run_import  # noqa: PLC0415

        def importer(content_dir, client, store):
            options = ImportOptions(content_dir=content_dir, draft_dirs={"drafts": "articles"})
            run_import(plan_import(options, client, store), client, store, apply=True)

        self.check(importer)


if __name__ == "__main__":
    unittest.main()
