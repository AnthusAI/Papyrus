"""Steps for features_backend/reference-list-paging.feature. Local directories only: no network, no AWS."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.home_page.task import _stale_list_files  # noqa: E402
from procedures.newsroom.tests.reader_privacy import scan_files  # noqa: E402
from procedures.newsroom.tests.reference_list_support import SNAPSHOT_KEY, list_files, project, record, snapshot  # noqa: E402
from procedures.newsroom.tests.test_reference_list_paging import HOOKS, chain, keys_in, rewrite, section_of  # noqa: E402

PLAIN = b'::band{size="bare"}\n::include{kind="references" select="recent" count="3"}\n'


def build(context, accepted: int, recommended: int, first: int, page_size: int, **options) -> None:
    context.site = project(snapshot(accepted, recommended), first=first, page_size=page_size, **options)
    context.add_cleanup(context.site.cleanup)
    context.document = json.loads(context.site.text(SNAPSHOT_KEY))
    context.before = list_files(context.site)


@given("a public site with {accepted:d} accepted and {recommended:d} recommended References, a first page of {first:d} and about {size:d} cards to a data file")
def _(context, accepted, recommended, first, size):
    build(context, accepted, recommended, first, size)


@given("a public site with {accepted:d} accepted References in {size:d}-card data files")
def _(context, accepted, size):
    build(context, accepted, 0, 6, size)


@given("the site has a page_finish hook that redraws every stock tile as its own card")
def _(context):
    context.site.cleanup()
    build(context, 60, 0, 4, 8, hooks="hooks.py", extra_files={"hooks.py": HOOKS.encode("utf-8")})


@given("a site that does not set homePage.references.paging")
def _(context):
    context.site.cleanup()
    context.site = project(snapshot(20, 5), paging=False, extra_files={"pages/wire.md": PLAIN})
    context.add_cleanup(context.site.cleanup)


@given("the site opted in but a page has only an ordinary references include")
def _(context):
    context.site.cleanup()
    context.site = project(snapshot(20, 5), paging=True, extra_files={"pages/wire.md": PLAIN})
    context.add_cleanup(context.site.cleanup)


@then('the "{select}" list on "{path}" shows {count:d} cards in the page itself')
def _(context, select, path, count):
    assert len(keys_in(section_of(context.site.text(path), select))) == count


@then('the "{select}" list has a link to a next static page and a polite live region')
def _(context, select):
    section = section_of(context.site.text("wire/index.html"), select)
    assert re.search(r'<a class="home-page-load-more" rel="next" href="/reference-lists/wire/%s/c[0-9a-f]+/"' % select, section), section[-600:]
    assert 'role="status" aria-live="polite"' in section


@then('following the "next" links from the first page reaches all {total:d} accepted References once each')
def _(context, total):
    page = context.site.text("wire/index.html")
    found, shown = re.search(r'rel="next" href="([^"]+)"', section_of(page, "recent")).group(1), keys_in(section_of(page, "recent"))
    while found:
        text = context.site.text(found.strip("/") + "/index.html")
        shown += keys_in(text)
        onward = re.search(r'rel="next" href="([^"]+)"', text)
        found = onward.group(1) if onward else None
    assert len(shown) == total and len(set(shown)) == total, (len(shown), len(set(shown)))


@then('the data files of the "recent" list give the remaining {remaining:d} References in the order of the first page\'s list')
def _(context, remaining):
    accepted = [r for r in context.document["references"] if r["status"] == "accepted"]
    expected = [r["key"] for r in sorted(accepted, key=lambda r: r["acceptedAt"], reverse=True)]
    shown = keys_in(section_of(context.site.text("wire/index.html"), "recent"))
    rest = [key for data in chain(context.site, "recent") for key in keys_in(data["html"])]
    assert len(rest) == remaining and shown + rest == expected


@then('the "recommended" list shows all {total:d} recommended References and none of the accepted ones')
def _(context, total):
    shown = keys_in(section_of(context.site.text("wire/index.html"), "recommended")) + [key for data in chain(context.site, "recommended") for key in keys_in(data["html"])]
    accepted = {r["key"] for r in context.document["references"] if r["status"] == "accepted"}
    assert len(shown) == total and not set(shown) & accepted


@then('each data file of the "recent" list carries exactly the cards of its static page')
def _(context):
    files = [name for name in list_files(context.site) if name.endswith(".json") and "/recent/" in name]
    assert files
    for name in files:
        data = json.loads(context.site.tree[name])
        assert data["html"] in context.site.text(name[: -len(".json")] + "/index.html")


@then("no page or data file contains a build marker")
def _(context):
    assert not [name for name, body in list_files(context.site).items() if b"papyrus:cards" in body]


@then('the first page and every data file of the "recent" list show the site\'s own card and no stock tile')
def _(context):
    page = context.site.text("wire/index.html")
    assert 'class="site-card"' in page and "home-page-tile" not in page
    data = chain(context.site, "recent")
    assert data and all('class="site-card"' in item["html"] and "home-page-tile" not in item["html"] for item in data)


@then("a page with an ordinary references include is byte for byte what it was, and no list file or script is published")
def _(context):
    assert not list_files(context.site) and "js/papyrus-reference-list.js" not in context.site.tree
    opted = project(snapshot(20, 5), paging=True, extra_files={"pages/wire.md": PLAIN})
    context.add_cleanup(opted.cleanup)
    assert {key: body for key, body in opted.tree.items() if key != "js/papyrus-reference-list.js"} == context.site.tree


@then("a paged include on that site stops the build and names the setting")
def _(context):
    try:
        project(snapshot(20, 5), paging=False).cleanup()
    except (ValueError, AssertionError) as error:
        assert "needs homePage.references.paging" in str(error)
    else:
        raise AssertionError("the build went on")


@then("that page loads no reference-list script and no list file exists")
def _(context):
    assert "papyrus-reference-list.js" not in context.site.text("wire/index.html") and not list_files(context.site)


def refused(source: bytes, message: str) -> None:
    try:
        project(snapshot(20, 5), extra_files={"pages/wire.md": source}).cleanup()
    except (ValueError, AssertionError) as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError("the build went on")


@then('a paged include with a "more" link is refused')
def _(context):
    refused(b'::include{kind="references" select="recent" paged="true" more="/x/"}\n', "cannot be paged and have a more link")


@then("a second paged list on one page with the same name is refused")
def _(context):
    refused(b'::include{kind="references" select="recent" paged="true"}\n::include{kind="references" select="recent" paged="true"}\n', "both named 'recent'")


@then("no data file, static page or Markdown twin of the paged lists holds a field the public snapshot does not publish")
def _(context):
    files = {key: body.decode("utf-8") for key, body in context.site.tree.items() if key.startswith("reference-lists/") or key == "wire/index.md"}
    assert files and scan_files(files, []) == {}
    assert not [name for name, text in files.items() if "starRating" in text or "curationStatusUpdatedBy" in text or "@" in text]


@then('the Markdown twin of "{path}" lists {count:d} References for each list and a "More" link')
def _(context, path, count):
    twin = context.site.text(path.replace(".html", ".md"))
    assert twin.count("- [Reference number") == 2 * count
    assert len(re.findall(r"\[More\]\(https://[^)]+/index\.md\)", twin)) == 2


@then("the Markdown of the first data page links back and on")
def _(context):
    twin = context.site.text("wire/index.md")
    first = re.search(r"\[More\]\(https://almanac\.example\.org/([^)]+)\)", twin).group(1)
    chunk = context.site.text(first)
    assert "[Back to The wire]" in chunk and "[Next](" in chunk


@when("a new Reference is accepted at the top of the order and every other Reference moves down one place")
def _(context):
    newest = record(9_999, "accepted", rank=0)
    newest.update(acceptedAt="2099-01-01T00:00:00.000Z", title="Brand new")
    context.document["references"].insert(0, newest)
    for position, found in enumerate(context.document["references"], start=1):
        found["rank"] = position
    context.report = rewrite(context.site, context.document)


@when("a Reference is removed from the middle of the list")
def _(context):
    context.document["references"].pop(1000)
    for position, found in enumerate(context.document["references"], start=1):
        found["rank"] = position
    context.report = rewrite(context.site, context.document)


@when("only the snapshot's freshness stamp changes")
def _(context):
    context.document["generatedAt"] = "2026-11-05T09:00:00.000Z"
    context.report = rewrite(context.site, context.document)


@when("the snapshot loses most of its References")
def _(context):
    context.document["references"] = context.document["references"][:20]
    context.report = rewrite(context.site, context.document)


def written_lists(context) -> list[str]:
    return [key for key in context.report.written if key.startswith("reference-lists/")]


@then("the page is rewritten and at most {limit:d} list files are written, out of about {total:d}")
def _(context, limit, total):
    assert "wire/index.html" in context.report.written
    assert 0 < len(written_lists(context)) <= limit * 3, written_lists(context)   # a chunk is three files: page, data and Markdown twin
    assert len(context.before) >= total - 5


@then("at most {limit:d} list files are written")
def _(context, limit):
    assert 0 < len(written_lists(context)) <= limit * 3, written_lists(context)


@then("every other list file is byte for byte what it was")
def _(context):
    after = list_files(context.site)
    changed = [key for key in after if context.before.get(key) != after[key]]
    assert len(changed) <= 4 * 3, changed


@then("no list file is written")
def _(context):
    assert written_lists(context) == []


@then("the files of the chunks that no longer exist are the ones found stale, and no other")
def _(context):
    expected = context.site.projector.reference_list_keys()
    stored = {key for key in list_files(context.site) if context.site.projector.owns_page_key(key)}
    stale = set(_stale_list_files(context.site.context))
    assert stale and stale == {key for key in stored if key not in expected}
