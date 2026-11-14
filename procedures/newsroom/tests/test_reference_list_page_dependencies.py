"""A Reference change re-projects exactly the list pages that show it, in the same home-page snapshot run (docs/home-page.md, "Freshness").

A page that places References is rewritten when what it shows changes, not whenever the snapshot file does: its input digest holds the public records its
lists place (and, for a paged list, the key that starts the first chunk), so a video's new picture rewrites the Videos list and the section list that show
that video and nothing else, and a change no list places rewrites no page. Synthetic data only: no network, no AWS.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from papyrus_content.home_page import incremental_test as corpus
from papyrus_content.home_page.export import public_key
from papyrus_content.home_page.state_store import DirtyBatch, MemoryStateStore
from papyrus_content.home_page.task import home_page_settings_of, run_home_page_snapshot
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite

SITE_DIRECTORY = FIXTURES / "home-page"
SECTIONS = {"music": "Music", "art": "Art"}
PAGES = {
    "videos": '::include{kind="references" select="recent" medium="video" count="2" paged="true" id="all" heading="Videos"}\n',
    "music-videos": '::include{kind="references" select="recent" medium="video" section="Music" count="6" heading="Music videos"}\n',
    "art-videos": '::include{kind="references" select="recent" medium="video" section="Art" count="6" heading="Art videos"}\n',
    "findings": '::include{kind="references" select="recent" notMedium="video" count="2" paged="true" id="all" heading="Findings"}\n',
}
#: The list pages, by object key; each has a Markdown twin beside it.
LIST_PAGES = {name: f"{name}/index.html" for name in PAGES}


class VideoCorpusClient(corpus.CorpusClient):
    """The corpus behind the snapshot: accepted articles, accepted videos filed under Music or Art, and pending References no list here places."""

    def __init__(self) -> None:
        super().__init__(0)
        self.next_index = 0

    def reference(self, *, accepted: bool, video: bool = False, section: str | None = None) -> str:
        row = self.add(self.next_index)
        self.next_index += 1
        status = "accepted" if accepted else "pending"
        row.update({
            "curationStatus": status, "curationStatusKey": f"{corpus.CORPUS}#{status}", "feedStateKey": None if accepted else f"{corpus.CORPUS}#unrated",
            "curationActorKind": "human" if accepted else None, "starRating": None, "curationSectionId": f"example-publication#{section}" if section else None,
        })
        if not accepted:
            row["predictedAcceptProbability"] = 0.9   # a pending Reference the Cyclotron recommends: public in the snapshot, on no list of these pages
        if video:
            row.update({"sourceUri": f"https://www.youtube.com/watch?v=video{self.next_index:06d}", "medium": "video"})
        return row["id"]

    def give_thumbnail(self, row_id: str) -> None:
        """What ``papyrus references capture-thumbnails`` writes: the stored copy's path on the Reference row."""
        digest = hashlib.sha256(self.rows[row_id]["lineageId"].encode("utf-8")).hexdigest()
        self.rows[row_id]["thumbnailPath"] = f"assets/reference-thumbnails/{digest[:16]}-{digest[16:28]}.jpg"

    def list_records(self, model: str) -> list[dict]:
        assert model == "NewsroomSection"
        self.requests["sections"] += 1
        return [{"id": slug, "storedId": f"example-publication#{slug}", "title": title} for slug, title in SECTIONS.items()]


def settings() -> dict:
    found = copy.deepcopy(json.loads((SITE_DIRECTORY / "projection.json").read_text(encoding="utf-8")))
    found["pages"] = [{"id": name, "path": name, "title": name.replace("-", " ").title(), "description": "A list of References.", "dependsOn": [], "source": f"pages/{name}.md"} for name in PAGES]
    found["homePage"]["references"]["paging"] = {"pageSize": 4}
    return found


def page_files() -> dict[str, bytes]:
    return {f"pages/{name}.md": ('::band{size="bare"}\n\n' + text).encode("utf-8") for name, text in PAGES.items()}


class VideoSite:
    """The site projected from the snapshot the first (full) run wrote; ``change`` runs the incremental task the stream trigger schedules."""

    def __init__(self) -> None:
        self.client = VideoCorpusClient()
        self.music_video = self.client.reference(accepted=True, video=True, section="music")
        self.art_video = self.client.reference(accepted=True, video=True, section="art")
        for _ in range(4):   # older videos and articles, so the paged lists have chunks after their first page
            self.oldest_video = self.client.reference(accepted=True, video=True, section="art")
            self.client.reference(accepted=True)
        self.pending = self.client.reference(accepted=False)
        for number, row_id in enumerate(self.client.rows):   # the order "recent" shows: the first References made are the newest accepted
            self.client.rows[row_id]["curationStatusUpdatedAt"] = f"2026-11-0{3 - number // 10}T{23 - number % 10:02d}:00:00.000Z"
            self.client.relations[self.client.rows[row_id]["lineageId"]][0]["createdAt"] = self.client.rows[row_id]["curationStatusUpdatedAt"]
        self.site = ProjectedSite(settings=settings(), content=SITE_DIRECTORY / "content", extra_files=page_files())
        self.store = MemoryStateStore()
        self.first = self._run(None)
        assert self.first["mode"] == "full" and self.first["written"] == [corpus.REFERENCES_KEY], self.first

    def _run(self, dirty: DirtyBatch | None) -> dict:
        self.site.writer.operations.clear()
        return run_home_page_snapshot(self.site.context, self.client, home_page_settings_of(self.site.projector), now=corpus.NOW, state_store=self.store, dirty=dirty)

    def change(self, *row_ids: str) -> dict:
        report = self._run(DirtyBatch(ids=frozenset(row_ids)))
        assert report["mode"] == "incremental", report
        return report

    def snapshot(self) -> dict:
        return json.loads(self.site.writer.get(corpus.REFERENCES_KEY))

    def record(self, row_id: str) -> dict:
        lineage = self.client.rows[row_id]["lineageId"]
        return next(found for found in self.snapshot()["references"] if found["key"] == public_key(lineage))

    def cleanup(self) -> None:
        self.site.cleanup()


def full_rebuild(built: VideoSite) -> ProjectedSite:
    """The same site projected from scratch (``project_all``) from the snapshot the incremental run left: what every page should be."""
    return ProjectedSite(settings=built.site.settings, content=SITE_DIRECTORY / "content", extra_files=page_files(), seed={corpus.REFERENCES_KEY: built.site.writer.get(corpus.REFERENCES_KEY)})


def rewritten_list_pages(report: dict) -> set[str]:
    return {name for name, key in LIST_PAGES.items() if key in report["rewritten"]}


@pytest.fixture
def video_site():
    built = VideoSite()
    yield built
    built.cleanup()


def test_a_videos_new_picture_rewrites_the_videos_list_and_its_section_list_and_nothing_else(video_site):
    assert not video_site.record(video_site.music_video).get("image")   # no copy yet, so no picture
    video_site.client.give_thumbnail(video_site.music_video)
    report = video_site.change(video_site.music_video)
    assert report["written"] == [corpus.REFERENCES_KEY]
    image = video_site.record(video_site.music_video)["image"]
    assert image and image.startswith("/assets/reference-thumbnails/")
    assert rewritten_list_pages(report) == {"videos", "music-videos"}, report["rewritten"]
    assert {"videos/index.md", "music-videos/index.md"} <= set(report["rewritten"])   # the twins go with their pages
    assert not [key for key in report["rewritten"] if key.startswith("reference-lists/")], report["rewritten"]   # the video is on the first page, in no chunk
    for name in ("videos", "music-videos"):
        assert image in video_site.site.text(LIST_PAGES[name])


def test_a_picture_for_a_video_past_the_first_page_rewrites_only_its_chunk(video_site):
    video_site.client.give_thumbnail(video_site.oldest_video)
    report = video_site.change(video_site.oldest_video)
    chunks = {key for key in report["rewritten"] if key.startswith("reference-lists/")}
    assert chunks and all(key.startswith("reference-lists/videos/all/") for key in chunks), report["rewritten"]
    assert rewritten_list_pages(report) == {"art-videos"}, report["rewritten"]   # it is on the Art list's only page, and past the Videos list's first


def test_a_change_no_list_places_rewrites_no_page(video_site):
    video_site.client.rows[video_site.pending]["title"] = "A pending Reference, retitled"
    report = video_site.change(video_site.pending)
    assert report["written"] == [corpus.REFERENCES_KEY]   # the snapshot carries it: it is public
    assert video_site.record(video_site.pending)["title"] == "A pending Reference, retitled"
    assert report["rewritten"] == [], report["rewritten"]
    assert report["pagesRewritten"] == 0


def test_the_pages_rewritten_are_the_pages_a_full_rebuild_would_change(video_site):
    video_site.client.give_thumbnail(video_site.art_video)
    report = video_site.change(video_site.art_video)
    rebuilt = full_rebuild(video_site)
    try:
        for key in LIST_PAGES.values():
            assert rebuilt.text(key) == video_site.site.text(key), key
    finally:
        rebuilt.cleanup()
    assert rewritten_list_pages(report) == {"videos", "art-videos"}, report["rewritten"]


# ------------------------------------------------------------------ section fronts that show a Reference grid

FRONTS = FIXTURES / "sectioned-fronts"
FRONTS_SNAPSHOT = FRONTS / "_data" / "home-page" / "references.json"


def fronts_site() -> ProjectedSite:
    return ProjectedSite(
        settings=json.loads((FRONTS / "projection.json").read_text(encoding="utf-8")), content=FIXTURES / "sectioned" / "content",
        extra_files={"pages/notes-front.md": (FRONTS / "pages" / "notes-front.md").read_bytes()}, seed={corpus.REFERENCES_KEY: FRONTS_SNAPSHOT.read_bytes()},
    )


def rewrite_snapshot(site: ProjectedSite, document: dict) -> list[str]:
    """What the snapshot task does after it writes a changed file: re-render the pages that read it whose digest changed."""
    from papyrus_content.home_page.task import reader_pages_of
    from papyrus_content.projection.engine import project_stale_listings

    (site.out / corpus.REFERENCES_KEY).write_bytes((json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    site.projector._home_page.reset()
    site.projector._plan_cache = None
    report = project_stale_listings(site.context, reader_pages_of(site.projector))
    assert report.ok, report.errors
    return list(report.written)


def test_a_section_front_with_a_reference_grid_is_rewritten_by_the_snapshot_run_when_its_grid_changes():
    site = fronts_site()
    try:
        assert "essays/index.html" in reader_keys(site)   # index.references: the front reads the snapshot
        assert "notes/index.html" not in reader_keys(site)   # its page file places no references include
        document = json.loads(FRONTS_SNAPSHOT.read_text(encoding="utf-8"))
        assert "Walls atlas" in site.text("essays/index.html")   # one of the two the grid shows
        next(found for found in document["references"] if found["title"] == "Walls atlas")["title"] = "Walls atlas, second edition"
        written = rewrite_snapshot(site, document)
        assert "essays/index.html" in written and "Walls atlas, second edition" in site.text("essays/index.html")
        other = next(found for found in document["references"] if found["section"] == "Notes")
        other["title"] = "Tide notes, retitled"
        assert "essays/index.html" not in rewrite_snapshot(site, document)   # a Notes Reference is not on the Essays grid
    finally:
        site.cleanup()


def reader_keys(site: ProjectedSite) -> frozenset[str]:
    from papyrus_content.home_page.task import reader_pages_of

    return reader_pages_of(site.projector)
