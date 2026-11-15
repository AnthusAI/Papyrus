"""Each language of a Story at its own address (features_backend/language-serving.feature).

A synthetic site in a temporary directory: the in-memory fake CMS, the standard projector built from a written projection.json and interface
strings, and a recording store. Nothing reaches AWS and no model runs."""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unicodedata
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.item_language import localization_lineage_id  # noqa: E402
from papyrus_content.page_refresh.paths import paths_for_page_keys  # noqa: E402
from papyrus_content.projection.engine import ProjectionContext, project, project_all  # noqa: E402
from papyrus_content.projection.source import PublishedContentSource  # noqa: E402
from papyrus_content.projection.standard.projector import StandardMarkusProjector  # noqa: E402
from papyrus_content.publishing import project_item_to_published, published_item_id_for  # noqa: E402
from papyrus_content.url_paths import encoded_path  # noqa: E402
from fake_client import FakeAuthoringClient  # noqa: E402
from incremental_site import FakeRedirectStore  # noqa: E402
from projection_fixtures import RecordingWriter  # noqa: E402

ORIGIN = "https://machines.example.test"
PROJECTION = {
    "site": {"name": "Machines on Machines", "description": "Machines writing about machines.", "productionUrl": ORIGIN, "language": "en"},
    "urls": {"style": "directory", "sections": {"articles": {"base": "articles", "label": "Articles"}, "wiki": {"base": "wiki", "label": "Wiki", "listEmpty": True}}},
    "sitemap": {"style": "index"},
    "environment": {"guard": False},
    "seo": {"defaultImage": "/assets/share/default.png", "defaultImageAlt": "Machines on Machines, in white capitals on navy."},
}
STRINGS = {
    "en": {"language.name": "English", "switcher.label": "Language"},
    "es-419": {"language.name": "Español", "site.name": "Máquinas Sobre Máquinas", "seo.defaultImage": "/assets/share/default-es.png", "seo.defaultImageAlt": "Máquinas Sobre Máquinas, en mayúsculas blancas sobre azul marino.", "switcher.label": "Idioma", "home.label": "Inicio", "listing.pageSuffix": " — página {page}",
               "site.description": "Máquinas que escriben sobre máquinas.", "section.articles.label": "Artículos", "section.wiki.label": "Conceptos",
               "translation.label": "Traducido por IA del {original}", "translation.original": "original en inglés",
               "listing.untranslated": "Todavía no hay traducciones aquí. Lee el {original}.", "listing.untranslatedOriginal": "índice en inglés"},
    "zh-Hans": {"language.name": "中文", "site.name": "机器论机器", "seo.defaultImage": "/assets/share/default-zh.png", "seo.defaultImageAlt": "机器论机器，白色大字，深蓝底。", "switcher.label": "语言", "home.label": "首页", "listing.pageSuffix": "（第 {page} 页）",
                "site.description": "机器书写机器。", "section.articles.label": "文章", "section.wiki.label": "概念",
                "translation.label": "由 AI 翻译自{original}", "translation.original": "英文原文",
                "listing.untranslated": "这里还没有译文。请阅读{original}。", "listing.untranslatedOriginal": "英文索引页"},
}
LANGUAGES = {"primary": "en", "enabled": ["en", "es-419", "zh-Hans"], "prefixes": {"es-419": "es", "zh-Hans": "zh"}, "public": ["en", "es-419", "zh-Hans"]}
NOW = "2026-11-13T00:00:00Z"
TITLES = {"es-419": "El sonido que puede delatar dónde vives", "zh-Hans": "能泄露你住在哪里的声音"}


class LanguageSite:
    def __init__(self, work: Path) -> None:
        self.work = work
        self.client = FakeAuthoringClient()
        self.languages = json.loads(json.dumps(LANGUAGES))
        self.strings = json.loads(json.dumps(STRINGS))
        self.store = RecordingWriter(work / "site")
        self.redirects = FakeRedirectStore()
        self.reports = []
        self.context = None
        self.authored_home = False
        self.notice = None   # the publication's notice (satire), when the scenario's site has one

    def build(self) -> None:
        static = self.work / "web"
        (static / "strings").mkdir(parents=True, exist_ok=True)
        projection = json.loads(json.dumps(PROJECTION))
        if self.authored_home:   # the site's home is a page of its own, as Machines on Machines' is
            projection["pages"] = [{"id": "home", "path": "", "title": "Machines on Machines", "description": "Home.", "source": "pages/home.md"}]
            (static / "pages").mkdir(exist_ok=True)
            (static / "pages" / "home.md").write_text("::raw\n<p>An authored home.</p>\n::endraw\n", encoding="utf-8")
        if self.notice:
            projection["site"]["notice"] = self.notice
            projection["feeds"] = {"formats": ["rss", "atom"]}
        (static / "projection.json").write_text(json.dumps(projection), encoding="utf-8")
        for path in (static / "strings").glob("*.json"):
            path.unlink()
        for tag, strings in self.strings.items():
            (static / "strings" / f"{tag}.json").write_text(json.dumps(strings, ensure_ascii=False), encoding="utf-8")
        self.client.tables.setdefault("EditorialCheckSettings", {})["settings"] = {"id": "settings", "settings": json.dumps({"languages": self.languages})}
        projector = StandardMarkusProjector.from_static_directory(static, environ={})
        self.context = ProjectionContext(source=PublishedContentSource(self.client), projector=projector, writer=self.store, redirect_store=self.redirects)

    def deploy(self) -> None:
        """The full render a deploy runs, before the scenario's publishes."""
        report = project_all(self.context)
        assert report.ok, report.errors

    def publish(self, item_id: str, *, lineage: str, slug: str, title: str, language: str, group: str, date: str | None = "2026-11-01",
                item_type: str = "article", section: str = "articles", entity_key: str | None = None, published_at: str = NOW) -> None:
        dated = f"date: '{date}'\n" if date else ""   # a translation made without one has no date of its own
        item = {"id": item_id, "lineageId": lineage, "type": item_type, "slug": slug, "section": section, "title": title, "status": "published",
                "language": language, "languageGroupId": group, "contentHash": f"{slug}-{language}",
                "metadata": {"frontMatterYaml": f"title: {json.dumps(title, ensure_ascii=False)}\n{dated}description: {json.dumps(title, ensure_ascii=False)}\n"
                                          + (f"entityKey: {entity_key}\n" if entity_key else "")},
                "bodyMarkus": f"{title}.\n"}
        self.client.tables.setdefault("Item", {})[item_id] = item
        published, _media = project_item_to_published(item, [], published_at=published_at, version_published_at=published_at, version_published_by="t", version_number=1)
        self.client.tables.setdefault("PublishedItem", {})[published["id"]] = published

    def unpublish(self, item_id: str) -> None:
        lineage = self.client.tables["Item"][item_id]["lineageId"]
        self.client.tables["PublishedItem"].pop(published_item_id_for(lineage))
        self.client.tables["Item"][item_id]["status"] = "draft"

    def project(self, item_id: str):
        report = project(self.context, item_id)
        assert report.ok, report.errors
        self.reports.append(report)
        return report

    def text(self, key: str) -> str:
        return (self.work / "site" / key).read_text(encoding="utf-8")

    def exists(self, key: str) -> bool:
        return (self.work / "site" / key).is_file()

    def keys(self) -> list[str]:
        root = self.work / "site"
        return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def _site(context) -> LanguageSite:
    return context.language_site


def _ensure_built(context) -> None:
    site = _site(context)
    if site.context is None:
        site.build()
        site.deploy()


def _publish_english(context, slug: str, title: str) -> None:
    _ensure_built(context)
    site = _site(context)
    site.publish(f"{slug}-v1", lineage=slug, slug=slug, title=title, language="en", group=slug)
    site.project(f"{slug}-v1")


def _publish_translation(context, language: str, slug: str) -> str:
    _ensure_built(context)
    site = _site(context)
    lineage = localization_lineage_id("the-sound", language)
    site.publish(f"{lineage}-v1", lineage=lineage, slug=slug, title=TITLES[language], language=language, group="the-sound")
    site.project(f"{lineage}-v1")
    return f"{lineage}-v1"


def _hreflang(html: str) -> list[tuple[str, str]]:
    return re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">', html)


def _canonical(html: str) -> str:
    return re.search(r'<link rel="canonical" href="([^"]+)">', html).group(1)


ENGLISH, SPANISH = "articles/the-sound/index.html", "es/articles/el-sonido/index.html"
CHINESE_SLUG = "能泄露你住在哪里的声音"
CHINESE = f"zh/articles/{CHINESE_SLUG}/index.html"


@given("a site that writes in English, Latin American Spanish and Simplified Chinese, with English at the root")
def step_site(context):
    work = tempfile.TemporaryDirectory()
    context.add_cleanup(work.cleanup)
    context.language_site = LanguageSite(Path(work.name))


@given('Spanish is served under "es" and Chinese under "zh", and both are public with complete interface strings')
def step_public(context):
    assert _site(context).languages["prefixes"] == {"es-419": "es", "zh-Hans": "zh"}


@given('the English article "{slug}" titled "{title}" is published')
def step_english(context, slug, title):
    _publish_english(context, slug, title)


@given("Spanish is enabled but not public")
def step_not_public(context):
    site = _site(context)
    site.languages["public"] = ["en", "zh-Hans"]
    shutil.rmtree(site.work / "site")   # the site as it is built when Spanish was never public: nothing written for it before
    site.store = RecordingWriter(site.work / "site")
    site.build()
    site.deploy()


@given('the Spanish interface strings lack "{key}"')
def step_strings_lack(context, key):
    site = _site(context)
    site.strings["es-419"].pop(key)
    site.build()


@given('its Spanish translation "{slug}" is published')
@when('its Spanish translation "{slug}" is published')
def step_spanish(context, slug):
    context.spanish_id = _publish_translation(context, "es-419", slug)


@given('its Chinese translation with the slug "{slug}" is published')
@when('its Chinese translation with the slug "{slug}" is published')
def step_chinese(context, slug):
    context.chinese_id = _publish_translation(context, "zh-Hans", slug)


@when('its Chinese translation is published with the slug "{slug}" written in decomposed jamo')
def step_decomposed(context, slug):
    decomposed = unicodedata.normalize("NFD", slug)
    assert decomposed != slug
    context.composed = slug
    context.chinese_id = _publish_translation(context, "zh-Hans", decomposed)


@when("the Spanish translation is unpublished")
def step_unpublish(context):
    site = _site(context)
    site.unpublish(context.spanish_id)
    site.project(context.spanish_id)


@when('the Chinese translation is renamed to "{slug}"')
def step_rename(context, slug):
    site = _site(context)
    lineage = localization_lineage_id("the-sound", "zh-Hans")
    site.client.tables["Item"][context.chinese_id]["slug"] = slug
    published = site.client.tables["PublishedItem"][published_item_id_for(lineage)]
    published["slug"] = slug
    published["versionNumber"] = 2
    context.new_slug = slug
    site.project(context.chinese_id)


@when("the multilingual site is projected")
def step_project_all(context):
    site = _site(context)
    try:
        project_all(site.context)
        context.refusal = None
    except ValueError as error:
        context.refusal = str(error)


@then('the English page is still at "{key}"')
def step_english_key(context, key):
    assert _site(context).exists(key), _site(context).keys()


@then('the Spanish page is at "{key}" and declares lang "{tag}"')
def step_spanish_key(context, key, tag):
    assert f'<html lang="{tag}"' in _site(context).text(key)


@then('no page of the site is under "/en/"')
def step_no_en(context):
    assert not any(key.startswith("en/") for key in _site(context).keys())


@then('the English page lists hreflang "en" and "es" (never "es-419", which search engines refuse) and x-default pointing at the English page')
def step_english_hreflang(context):
    found = _hreflang(_site(context).text(ENGLISH))
    assert found == [("en", f"{ORIGIN}/articles/the-sound/"), ("es", f"{ORIGIN}/es/articles/el-sonido/"), ("x-default", f"{ORIGIN}/articles/the-sound/")], found


@then("the Spanish page lists the same hreflang links")
def step_spanish_hreflang(context):
    assert _hreflang(_site(context).text(SPANISH)) == _hreflang(_site(context).text(ENGLISH))


@then("neither page lists Chinese")
def step_no_chinese(context):
    for key in (ENGLISH, SPANISH):
        assert "zh-Hans" not in dict(_hreflang(_site(context).text(key)))


@then("each page is canonical to its own address")
def step_canonical(context):
    assert _canonical(_site(context).text(ENGLISH)) == f"{ORIGIN}/articles/the-sound/"
    assert _canonical(_site(context).text(SPANISH)) == f"{ORIGIN}/es/articles/el-sonido/"


@then('the Spanish page says og:locale "{locale}" and its JSON-LD inLanguage is "{tag}"')
def step_locale(context, locale, tag):
    html = _site(context).text(SPANISH)
    assert f'<meta property="og:locale" content="{locale}">' in html and '<meta property="og:locale:alternate" content="en">' in html
    assert f'"inLanguage":"{tag}"' in html


@then('the Spanish page\'s alternates name each language in itself: "{english}" and "{spanish}"')
def step_names(context, english, spanish):
    site = _site(context)
    projector = site.context.projector
    index = site.context.source.site_index()
    item = site.context.source.published_item(context.spanish_id)
    projector.item_pages(item, index)
    view = projector._language_view(index)
    names = [alternate.name for alternate in view.item_alternates(item.summary)]
    assert names == [english, spanish], names


@then("the projection of the Spanish translation also wrote the English page")
def step_sibling_written(context):
    assert ENGLISH in _site(context).reports[-1].written, _site(context).reports[-1].written


@then("it wrote no other article page")
def step_only_siblings(context):
    pages = [key for key in _site(context).reports[-1].written if "/articles/" in f"/{key}" and key.endswith("/index.html") and key.count("/") >= 2
             and not key.startswith(("articles/index", "es/articles/index", "zh/articles/index"))]
    assert sorted(pages) == sorted([ENGLISH, SPANISH]), pages


@then("the Spanish page is gone")
def step_gone(context):
    assert not _site(context).exists(SPANISH)


@then("the English page lists no hreflang links")
def step_no_hreflang(context):
    assert _hreflang(_site(context).text(ENGLISH)) == []


def _links(html: str) -> set[str]:
    return set(re.findall(r'href="(/[^"]*)"', html))


@then('the English home and the English articles listing link "the-sound" and "the-other" and no Spanish page')
def step_english_listings(context):
    for key in ("index.html", "articles/index.html"):
        links = _links(_site(context).text(key))
        assert {"/articles/the-sound/", "/articles/the-other/"} <= links and not any(link.startswith("/es/articles/") for link in links), (key, links)


@then('the Spanish home and the Spanish articles listing link only "el-sonido"')
def step_spanish_listings(context):
    for key in ("es/index.html", "es/articles/index.html"):
        links = {link for link in _links(_site(context).text(key)) if "/articles/" in link and link.count("/") > 3}
        assert links == {"/es/articles/el-sonido/"}, (key, links)


@then("the English home and the Spanish home name each other in hreflang")
def step_home_hreflang(context):
    expected = [("en", f"{ORIGIN}/"), ("es", f"{ORIGIN}/es/"), ("x-default", f"{ORIGIN}/")]
    assert _hreflang(_site(context).text("index.html")) == expected, _hreflang(_site(context).text("index.html"))
    assert _hreflang(_site(context).text("es/index.html")) == expected


@then('the sitemap index lists "{first}" and "{second}"')
def step_sitemap_index(context, first, second):
    index = _site(context).text("sitemap-index.xml")
    assert f"<loc>{ORIGIN}/{first}</loc>" in index and f"<loc>{ORIGIN}/{second}</loc>" in index, index


@then("the Spanish sitemap lists the Spanish page and no English one")
def step_spanish_sitemap(context):
    sitemap = _site(context).text("es/sitemap-0.xml")
    assert f"{ORIGIN}/es/articles/el-sonido/" in sitemap and "/the-sound/" not in sitemap.replace("/es/", "")


@then('there is no page under "es/"')
def step_no_es(context):
    assert not any(key.startswith("es/") for key in _site(context).keys()), _site(context).keys()


@then('the projection is refused naming "{text}"')
def step_refused(context, text):
    assert context.refusal and text in context.refusal, context.refusal


@then('the Chinese page\'s object key is "{key}" in Unicode NFC')
def step_chinese_key(context, key):
    assert unicodedata.is_normalized("NFC", key)
    assert key in _site(context).keys(), _site(context).keys()


@then("its canonical address, its hreflang links and its sitemap entry are the percent-encoded form of that key")
def step_chinese_encoded(context):
    site = _site(context)
    encoded = f"{ORIGIN}{encoded_path('/zh/articles/' + CHINESE_SLUG + '/')}"
    assert "%E8%83%BD" in encoded and CHINESE_SLUG not in encoded
    html = site.text(CHINESE)
    assert _canonical(html) == encoded
    assert ("zh-Hans", encoded) in _hreflang(html) and ("zh-Hans", encoded) in _hreflang(site.text(ENGLISH))
    assert f"<loc>{encoded}</loc>" in site.text("zh/sitemap-0.xml")


@then("the Chinese home links the page by the same percent-encoded address")
def step_chinese_home(context):
    assert f'href="{encoded_path("/zh/articles/" + CHINESE_SLUG + "/")}"' in _site(context).text("zh/index.html")


@then("the edge invalidation paths of the page are percent-encoded, one path per form, each counted once")
def step_invalidation(context):
    paths = paths_for_page_keys([CHINESE])
    encoded = encoded_path(f"/zh/articles/{CHINESE_SLUG}/")
    assert paths == [encoded + "index.html", encoded], paths
    assert all(path.isascii() for path in paths)


@then('the Chinese page\'s object key holds the composed "{slug}" and no decomposed character')
def step_composed(context, slug):
    keys = [key for key in _site(context).keys() if key.startswith("zh/articles/") and key.endswith("/index.html") and key != "zh/articles/index.html"]
    assert keys == [f"zh/articles/{slug}/index.html"], keys
    assert all(unicodedata.is_normalized("NFC", key) for key in keys)


@then("the redirect store sends the encoded old address to the encoded new address")
def step_redirect(context):
    mapping = _site(context).redirects.mapping
    old, new = encoded_path(f"/zh/articles/{CHINESE_SLUG}/"), encoded_path(f"/zh/articles/{context.new_slug}/")
    assert mapping.get(old) == new, mapping
    assert all(source.isascii() and target.isascii() for source, target in mapping.items())


@then("the English page's hreflang names the new Chinese address")
def step_hreflang_renamed(context):
    assert ("zh-Hans", ORIGIN + encoded_path(f"/zh/articles/{context.new_slug}/")) in _hreflang(_site(context).text(ENGLISH))


def _spanish_page(context):
    site = _site(context)
    projector = site.context.projector
    index = site.context.source.site_index()
    edition = projector._edition_for(site.context.source.published_item(context.spanish_id).summary)
    projector._editions_of(index)
    captured = {}
    original = edition._render

    def capture(page):
        captured["page"] = page
        return original(page)

    edition._render = capture
    try:
        projector.item_pages(site.context.source.published_item(context.spanish_id), index)
    finally:
        del edition._render
    return captured["page"]


@then('from the Spanish page a link to "{path}" goes to "{target}" and stays in Spanish')
def step_link_stays(context, path, target):
    assert _spanish_page(context).link_in_language(path) == (target, False)


@then('from the Spanish page a link to "{path}" stays where it is and is marked as leaving Spanish')
def step_link_leaves(context, path):
    assert _spanish_page(context).link_in_language(path) == (path, True)


@given('the English Concept page "{slug}" is published in the wiki')
def step_wiki_english(context, slug):
    _ensure_built(context)
    site = _site(context)
    site.publish(f"{slug}-v1", lineage=slug, slug=slug, title="Abliteration", language="en", group=slug, item_type="wiki_page", section="wiki")
    site.project(f"{slug}-v1")
    context.wiki_slug = slug


@when('its Spanish translation "{slug}" of the Concept page is published')
def step_wiki_spanish(context, slug):
    site = _site(context)
    lineage = localization_lineage_id(context.wiki_slug, "es-419")
    site.publish(f"{lineage}-v1", lineage=lineage, slug=slug, title="Abliteración", language="es-419", group=context.wiki_slug, item_type="wiki_page", section="wiki")
    site.project(f"{lineage}-v1")


@then('the English Concept page stays at "{key}" and the Spanish one is at "{spanish}"')
def step_wiki_keys(context, key, spanish):
    site = _site(context)
    assert site.exists(key) and site.exists(spanish), site.keys()
    assert ("es", f"{ORIGIN}/" + spanish[: -len("index.html")]) in _hreflang(site.text(key))


@given("the English home is an authored page")
def step_authored_home(context):
    _site(context).authored_home = True


@then('the Spanish "{key}" page exists and is not indexed')
def step_empty_exists(context, key):
    html = _site(context).text(key)
    assert '<meta name="robots" content="noindex' in html, key


@then('the Spanish "{key}" page says in Spanish that nothing is translated yet and links to the English "{english}"')
def step_notice(context, key, english):
    html = _site(context).text(key)
    assert f'class="markus-untranslated"' in html and "Todavía no hay traducciones aquí." in html, key
    assert f'<a href="{english}" hreflang="en">índice en inglés</a>' in html, key


@then('the "{key}" page lists no hreflang links')
def step_page_no_hreflang(context, key):
    assert _hreflang(_site(context).text(key)) == [], key


@then('the Spanish "{key}" page is indexed and has no notice')
def step_indexed(context, key):
    html = _site(context).text(key)
    assert '<meta name="robots"' not in html and "markus-untranslated" not in html, key


@then('the "{key}" page names the Spanish page in hreflang')
def step_names_spanish(context, key):
    tags = dict(_hreflang(_site(context).text(key)))
    assert "es" in tags and "es-419" not in tags and "x-default" in tags, tags


@then("the sitemap index lists no Spanish or Chinese sitemap")
def step_no_language_sitemap(context):
    index = _site(context).text("sitemap-index.xml")
    assert "es/sitemap" not in index and "zh/sitemap" not in index, index


@then('the Concepts listing is offered in each language at "{english}", "{spanish}" and "{chinese}"')
def step_concepts_alternates(context, english, spanish, chinese):
    site = _site(context)
    view = site.context.projector._language_view(site.context.source.site_index())
    assert [alternate.url for alternate in view.listing_alternates("wiki")] == [english, spanish, chinese], view.listing_alternates("wiki")


@given('the English Concept page "{slug}" is published and the English article "the-sound" is about it')
def step_concept_and_edge(context, slug):
    _ensure_built(context)
    site = _site(context)
    site.publish(f"{slug}-v1", lineage=slug, slug=slug, title="Human oversight", language="en", group=slug, item_type="wiki_page", section="wiki", entity_key=slug)
    site.project(f"{slug}-v1")
    context.wiki_slug = slug
    node = f"node-{slug}"
    site.client.tables.setdefault("SemanticNode", {})[node] = {"id": node, "status": "accepted", "nodeKey": f"editor_concept--{slug}"}
    site.client.tables.setdefault("SemanticRelation", {})["relation-1"] = {
        "id": "relation-1", "subjectKind": "item", "subjectLineageId": "the-sound", "subjectStateKey": "item#the-sound#current", "predicate": "mentions",
        "objectKind": "semanticNode", "objectLineageId": f"editor_concept--{slug}", "objectId": node, "relationState": "current",
    }


def _chips(context, tag: str, slug: str):
    site = _site(context)
    projector = site.context.projector
    index = site.context.source.site_index()
    projector._editions_of(index)
    own = projector._own_site(index, tag)
    page = next(summary for summary in index.items if summary.language == tag and summary.slug == slug)
    owner = projector if tag == "en" else projector._editions[tag]
    return owner._concept_links(own, page)


@then('the Spanish article has no concept chip and the English article has the chip "{slug}" counting one Story')
def step_chips_before(context, slug):
    assert _chips(context, "es-419", "el-sonido") == ()
    assert [(link["slug"], link["stories"]) for link in _chips(context, "en", "the-sound")] == [(slug, 1)]


@when('the Concept page "{slug}" is translated into Spanish as "{spanish}"')
def step_concept_translated(context, slug, spanish):
    site = _site(context)
    lineage = localization_lineage_id(slug, "es-419")
    site.publish(f"{lineage}-v1", lineage=lineage, slug=spanish, title="Supervisión humana", language="es-419", group=slug, item_type="wiki_page", section="wiki", entity_key=slug)
    site.project(f"{lineage}-v1")


@then('the Spanish article has the chip "{slug}" linked at "{href}"')
def step_chip_spanish(context, slug, href):
    assert [(link["slug"], link["href"]) for link in _chips(context, "es-419", "el-sonido")] == [(slug, href)], _chips(context, "es-419", "el-sonido")


# ---------------------------------------------------------------------------------------------- a language edition ranks its Stories as their originals rank

RANKED_DATES = {"alpha-star": "2026-11-09", "mid-plain": "2026-11-11", "new-plain": "2026-11-12"}


def _ranked_site(context):
    from papyrus_content.projection.story_stars import MemoryStarStore

    _ensure_built(context)
    site = _site(context)
    site.context.source.star_store = MemoryStarStore()
    site.context.projector.clock = lambda: __import__("datetime").date(2026, 11, 13)
    return site


@given('the English articles "alpha-star", "mid-plain" and "new-plain" are published on the 9th, the 11th and the 12th')
def step_ranked_english(context):
    site = _ranked_site(context)
    for slug, day in RANKED_DATES.items():
        site.publish(f"{slug}-v1", lineage=slug, slug=slug, title=slug, language="en", group=slug, date=day)
        site.project(f"{slug}-v1")


@given('the editors rated "alpha-star" 5 stars')
def step_ranked_stars(context):
    _site(context).context.source.star_store.record({"alpha-star": 5})


@when('their Spanish translations are published on the 15th without a date of their own, "new-plain" first and "alpha-star" last')
def step_ranked_spanish(context):
    site = _site(context)
    for slug in ("new-plain", "mid-plain", "alpha-star"):
        lineage = localization_lineage_id(slug, "es-419")
        site.publish(f"{lineage}-v1", lineage=lineage, slug=f"es-{slug}", title=f"es {slug}", language="es-419", group=slug, date=None,
                     published_at="2026-11-15T00:00:00Z")
        site.project(f"{lineage}-v1")
    site.deploy()   # a release renders every page again, with the rating


def _listed(html: str, prefix: str) -> list[str]:
    seen: list[str] = []
    for link in re.findall(r'href="(/[^"]*)"', html):
        if link.startswith(prefix) and link.count("/") == prefix.count("/") + 1 and link not in seen:
            seen.append(link)
    return seen


@then('the English articles listing and home list "alpha-star", "new-plain", "mid-plain" in that order')
def step_ranked_english_order(context):
    for key in ("articles/index.html", "index.html"):
        assert _listed(_site(context).text(key), "/articles/") == [f"/articles/{slug}/" for slug in ("alpha-star", "new-plain", "mid-plain")], (key, _listed(_site(context).text(key), "/articles/"))


@then("the Spanish articles listing and home list their translations in that same order")
def step_ranked_spanish_order(context):
    for key in ("es/articles/index.html", "es/index.html"):
        found = _listed(_site(context).text(key), "/es/articles/")
        assert found == [f"/es/articles/es-{slug}/" for slug in ("alpha-star", "new-plain", "mid-plain")], (key, found)


@then('the Spanish card of "alpha-star" shows the date of its original, the 9th')
def step_ranked_date(context):
    html = _site(context).text("es/articles/index.html")
    card = re.search(r'es-alpha-star/.*?datetime="([^"]+)"', html, re.S)
    assert card and card.group(1) == "2026-11-09", card and card.group(1)


@given('the site\'s notice is "{label}" and "{text}" and Spanish says "{label_es}" and "{text_es}"')
def step_notice(context, label, text, label_es, text_es):
    site = _site(context)
    site.notice = {"label": label, "text": text}
    site.strings["es-419"]["notice.label"] = label_es
    site.strings["es-419"]["notice.text"] = text_es
    site.strings["zh-Hans"]["notice.label"] = label_es
    site.strings["zh-Hans"]["notice.text"] = text_es
    site.build()


@then("the Spanish page, its Markdown twin, the Spanish feeds and the Spanish page's structured data say the notice in Spanish and not in English")
def step_notice_spanish(context):
    site = _site(context)
    page = site.text("es/articles/el-sonido/index.html")
    assert "Sátira" in page and "Todo lo que hay en este sitio es inventado." in page
    assert '"genre":"Sátira"' in page, "structured data"
    twin = site.text("es/articles/el-sonido/index.md")
    assert "> **Sátira.** Todo lo que hay en este sitio es inventado." in twin, twin
    assert "Everything on this site is invented" not in twin
    for key in ("es/feed.xml", "es/atom.xml"):
        feed = site.text(key)
        assert "Sátira. " in feed and "Satire. " not in feed, (key, feed[:600])


@then("the English page, its Markdown twin and the English feed still say it in English")
def step_notice_english(context):
    site = _site(context)
    assert '"genre":"Satire"' in site.text("articles/the-sound/index.html")
    assert "> **Satire.** Everything on this site is invented." in site.text("articles/the-sound/index.md")
    assert "Satire. " in site.text("feed.xml")


@when('its Spanish translation "{slug}" and its Chinese translation "{chinese}" are published')
def step_both_published(context, slug, chinese):
    _publish_translation(context, "es-419", slug)
    _publish_translation(context, "zh-Hans", chinese)


@then('the {edition} home says its name "{name}" in its title, og:site_name, structured data and feed')
def step_name_everywhere(context, edition, name):
    site = _site(context)
    prefix = {"English": "", "Spanish": "es/", "Chinese": "zh/"}[edition]
    home = site.text(f"{prefix}index.html")
    assert f'<meta property="og:site_name" content="{name}">' in home, home[:2500]
    assert re.search(rf"<title>[^<]*{re.escape(name)}</title>", home), re.search(r"<title>[^<]*", home)
    assert f'"@type":"WebSite","name":"{name}"' in home.replace(" ", "") or f'"name":"{name}"' in home, home
    assert f"<title>{name}" in site.text(f"{prefix}feed.xml"), site.text(f"{prefix}feed.xml")[:400]


@then('the {edition} home lists "{first}" and "{second}" as alternate names')
def step_alternate_names(context, edition, first, second):
    prefix = {"English": "", "Spanish": "es/", "Chinese": "zh/"}[edition]
    home = _site(context).text(f"{prefix}index.html")
    block = next(m for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', home, re.S) if '"WebSite"' in m)
    names = json.loads(block)["alternateName"]
    assert first in names and second in names, names


@then('the Spanish article says its publisher "{name}" with alternate names "{english}" and "{chinese}"')
def step_publisher(context, name, english, chinese):
    page = _site(context).text("es/articles/el-sonido/index.html")
    block = next(m for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S) if '"publisher"' in m)
    publisher = json.loads(block)["publisher"]
    assert publisher["name"] == name and publisher["alternateName"] == [english, chinese], publisher


@then("each home shares its own language's picture, with alt text in that language")
def step_share_picture(context):
    site = _site(context)
    for prefix, image, alt in (("", "/assets/share/default.png", "Machines on Machines, in white"), ("es/", "/assets/share/default-es.png", "Máquinas Sobre Máquinas, en mayúsculas"), ("zh/", "/assets/share/default-zh.png", "机器论机器，白色大字")):
        home = site.text(f"{prefix}index.html")
        assert f'<meta property="og:image" content="{ORIGIN}{image}">' in home, (prefix, re.findall(r'og:image" content="[^"]*', home))
        assert f'<meta property="og:image:alt" content="{alt}' in home, prefix
