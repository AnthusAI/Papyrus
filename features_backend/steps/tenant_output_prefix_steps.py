from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.engine import ProjectionContext, project_all  # noqa: E402
from papyrus_content.projection.source import PublishedContentSource  # noqa: E402
from papyrus_content.projection.writers import LocalDirectoryWriter, OutputPrefixError  # noqa: E402
from procedures.newsroom.tests.projection_fixtures import tree_digests  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite  # noqa: E402


def project_into(site: ProjectedSite, directory: Path, prefix: str) -> None:
    context = ProjectionContext(
        source=PublishedContentSource(site.client),
        projector=site.projector,
        writer=LocalDirectoryWriter(directory, prefix),
        redirect_store=None,
    )
    report = project_all(context)
    assert report.ok, report.errors


@given("a published standard site with a story")
def prefix_site(context) -> None:
    context.prefix_site = ProjectedSite("flat")   # projected once without a prefix: the dedicated-site tree
    context.add_cleanup(context.prefix_site.cleanup)
    context.prefix_out = Path(tempfile.mkdtemp(prefix="prefixed-out-"))
    context.prefix = ""
    context.prefix_neighbour = None


@given("a site with no output prefix")
def no_prefix(context) -> None:
    context.prefix = ""


@given('output prefix "{prefix}"')
def with_prefix(context, prefix: str) -> None:
    context.prefix = prefix


@given('another site already stored under "{prefix}"')
def neighbour(context, prefix: str) -> None:
    (context.prefix_out / prefix).mkdir(parents=True)
    (context.prefix_out / prefix / "index.html").write_bytes(b"beta home")
    context.prefix_neighbour = prefix


@when("it is projected")
@when("the prefixed site is projected")
def prefix_projected(context) -> None:
    project_into(context.prefix_site, context.prefix_out, context.prefix)


@then("the key listing is byte-identical to before")
def identical_to_before(context) -> None:
    before = context.prefix_site.digests()   # the same projection written by a writer that has no prefix concept in play
    assert before, "the dedicated tree is empty"
    after = tree_digests(context.prefix_out)
    # state objects are kept in memory by the recording writer; compare the pages
    pages = {key: digest for key, digest in after.items() if not key.startswith("_papyrus/")}
    assert pages == before, (sorted(set(pages) ^ set(before)), [key for key in before if pages.get(key) != before[key]])


@then('every key starts with "{prefix}"')
def every_key(context, prefix: str) -> None:
    keys = [key for key in tree_digests(context.prefix_out) if context.prefix_neighbour is None or not key.startswith(context.prefix_neighbour)]
    assert keys, "nothing was written"
    outside = [key for key in keys if not key.startswith(prefix)]
    assert not outside, outside


@then("the prefixed site holds the same pages as the unprefixed site, each with identical content")
def same_pages(context) -> None:
    before = context.prefix_site.digests()
    after = {key[len(context.prefix) :]: digest for key, digest in tree_digests(context.prefix_out).items() if key.startswith(context.prefix) and not key.startswith(context.prefix + "_papyrus/")}
    assert after == before, (sorted(set(after) ^ set(before)), [key for key in before if after.get(key) != before[key]])


@then("the prefixed site holds the not-found page, robots.txt and the sitemap under its prefix")
def special_files(context) -> None:
    keys = set(tree_digests(context.prefix_out))
    for name in ("404.html", "robots.txt", "sitemap.xml"):
        assert context.prefix + name in keys, (name, sorted(keys)[:30])
        assert name not in keys, name


@when("a key that climbs out of the prefix is written")
def climbing_key(context) -> None:
    writer = LocalDirectoryWriter(context.prefix_out, context.prefix)
    context.refusals = []
    for key in ("../beta/index.html", "/etc/passwd", "a/../../b.html"):
        try:
            writer.put(key, b"x")
        except OutputPrefixError as error:
            context.refusals.append(str(error))


@then('the writer refuses it and nothing is written outside "{prefix}"')
def refused(context, prefix: str) -> None:
    assert len(context.refusals) == 3, context.refusals
    outside = [path for path in context.prefix_out.rglob("*") if path.is_file() and not path.relative_to(context.prefix_out).as_posix().startswith(prefix)]
    assert not outside, outside


@then('the projection lists only the keys under "{prefix}"')
def lists_only(context, prefix: str) -> None:
    listed = LocalDirectoryWriter(context.prefix_out, prefix).list()
    assert listed
    assert all(not entry.key.startswith("sites/") for entry in listed), [entry.key for entry in listed][:5]
    assert "index.html" in {entry.key for entry in listed}


@then('"{prefix}" is untouched')
def untouched(context, prefix: str) -> None:
    files = sorted(path.relative_to(context.prefix_out).as_posix() for path in (context.prefix_out / prefix).rglob("*") if path.is_file())
    assert files == [prefix + "index.html"], files
    assert (context.prefix_out / prefix / "index.html").read_bytes() == b"beta home"
