from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.engine import project_all, reconcile  # noqa: E402
from papyrus_content.projection.writers import STATE_PREFIX  # noqa: E402
from papyrus_content.projection.standard.projector import StandardMarkusProjector  # noqa: E402
from procedures.newsroom.tests import knowledge_fixtures  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite, static_directory  # noqa: E402

ROOT_RELATIVE = re.compile(r'\b(?:href|src)="(/(?!/)[^"]*)"')


def listed(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


@given('a standard site with url style "{style}", production URL "{origin}" and base path "{base}"')
def based_settings(context, style: str, origin: str, base: str) -> None:
    context.based_settings = {
        "site": {"name": "Example", "productionUrl": origin},
        "urls": {"style": style, "basePath": base},
        "publicData": {"searchIndex": True, "latest": True},
    }
    context.based_aliases = []
    context.based_content = Path(tempfile.mkdtemp(prefix="based-content-"))


@given('a published item "{slug}" with the tag "{tag}"')
def based_item(context, slug: str, tag: str) -> None:
    context.based_slug = slug
    context.based_tag = tag


@given('the based site has a nav link "{label}" to "{href}"')
def based_nav_link(context, label: str, href: str) -> None:
    context.based_settings["nav"] = {"links": [{"label": label, "href": href}]}


@given('the item "{slug}" has the alias "{alias}"')
def based_alias(context, slug: str, alias: str) -> None:
    context.based_aliases.append(alias)


@given('the based site has a knowledge page and a snapshot stored under "{prefix}"')
def based_knowledge(context, prefix: str) -> None:
    context.based_settings["pages"] = [{"id": "knowledge", "path": "knowledge", "title": "Knowledge", "source": "knowledge.md"}]
    context.based_files = {"knowledge.md": '::band{size="bare"}\n# Knowledge\n\n::include{kind="block" name="knowledge-topic-count"}\n'}
    directory = knowledge_fixtures.write(Path(tempfile.mkdtemp(prefix="based-knowledge-")))
    context.based_seed = {prefix + path.relative_to(directory).as_posix(): path.read_bytes() for path in sorted(directory.rglob("*")) if path.is_file()}


@when("the based site is projected")
def project_based_site(context) -> None:
    aliases = "".join(f"  - {alias}\n" for alias in context.based_aliases)
    (context.based_content / f"{context.based_slug}.md").write_text(
        f"---\ntitle: Hello\ndate: '2026-10-01'\ndescription: A first article.\ntags: [{context.based_tag}]\n"
        + (f"aliases:\n{aliases}" if aliases else "")
        + "---\n\nThe body of the first article.\n",
        encoding="utf-8",
    )
    context.site = ProjectedSite(
        settings=context.based_settings,
        content=context.based_content,
        extra_files=getattr(context, "based_files", None),
        seed=getattr(context, "based_seed", None),
    )
    context.add_cleanup(context.site.cleanup)


@when("the based site is reconciled")
def reconcile_based_site(context) -> None:
    report = reconcile(context.site.context)
    assert not report.orphan_pages, report.orphan_pages


@then('the based site still holds "{keys}"')
def based_still_holds(context, keys: str) -> None:
    missing = [key for key in listed(keys) if key not in context.site.tree]
    assert not missing, (missing, sorted(context.site.tree))


@then('the based site does not own "{key}"')
def based_does_not_own(context, key: str) -> None:
    assert not context.site.projector.owns_page_key(key)


@then("the based site holds no snapshot file at the bucket root")
def based_no_root_snapshot(context) -> None:
    root = [key for key in context.site.tree if key.startswith("_data/")]
    assert not root, root


@then('the based site has these pages: "{keys}"')
def based_pages(context, keys: str) -> None:
    tree = context.site.tree
    missing = [key for key in listed(keys) if key not in tree]
    assert not missing, (missing, sorted(tree))


@then('every object of the based site outside "{state}" is under "{prefix}" except "{exceptions}"')
def based_objects_under(context, state: str, prefix: str, exceptions: str) -> None:
    assert state == STATE_PREFIX, (state, STATE_PREFIX)
    allowed = set(listed(exceptions))
    outside = [key for key in context.site.tree if not key.startswith((state, prefix)) and key not in allowed]
    assert not outside, outside


@then('every root-relative href and src in "{key}" starts with "{prefix}"')
def based_links(context, key: str, prefix: str) -> None:
    found = ROOT_RELATIVE.findall(context.site.text(key))
    assert found, f"no root-relative links in {key}"
    outside = [url for url in found if not url.startswith(prefix)]
    assert not outside, outside


@then('the based page "{key}" says "{text}"')
def based_page_says(context, key: str, text: str) -> None:
    body = context.site.text(key)
    assert text in body, body[:4000]


@then('the based site redirects "{source}" to "{target}"')
def based_redirect(context, source: str, target: str) -> None:
    assert context.site.redirects.mapping.get(source) == target, context.site.redirects.mapping


@when('the redirect store maps "{source}" to "{target}" from an earlier layout')
def stale_redirect(context, source: str, target: str) -> None:
    context.site.redirects.mapping[source] = target


@when("everything on the based site is projected again")
def project_based_site_again(context) -> None:
    context.site.report = project_all(context.site.context)


@then('the based site does not redirect "{source}"')
def based_no_redirect(context, source: str) -> None:
    assert source not in context.site.redirects.mapping, context.site.redirects.mapping


@when('the settings of a site with base path "{base}" are read')
def read_bad_base(context, base: str) -> None:
    read_settings(context, {"site": {"name": "Example"}, "urls": {"basePath": base}})


@when('the settings of a site with base path "{base}" and an images section are read')
def read_base_with_images(context, base: str) -> None:
    read_settings(context, {"site": {"name": "Example"}, "urls": {"basePath": base}, "images": {}})


def read_settings(context, settings: dict) -> None:
    work = Path(tempfile.mkdtemp(prefix="based-settings-"))
    context.based_error = None
    try:
        StandardMarkusProjector.from_static_directory(static_directory(work, settings), environ={"PAPYRUS_SITE_PUBLIC_URL": ""})
    except ValueError as error:
        context.based_error = error


@then('they are refused with a message that names "{name}"')
def refused(context, name: str) -> None:
    assert context.based_error is not None, "the settings were accepted"
    assert name in str(context.based_error), str(context.based_error)
