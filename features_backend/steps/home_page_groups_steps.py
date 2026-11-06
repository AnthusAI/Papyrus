from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from procedures.newsroom.tests import test_home_page_groups as support  # noqa: E402
from procedures.newsroom.tests.standard_frontend_content_support import DirectorySite, item, settings  # noqa: E402

GROUP = support.GROUP


def _project(context, name: str, body: str) -> str:
    site = support.project({name: body})
    context.add_cleanup(site.cleanup)
    return site.text(f"{name}/index.html")


@given('a site with the sections "privacy", "law" and "science"')
def sections(context) -> None:
    context.sections = ("privacy", "law", "science")


@given('articles and posts in those sections, where "law" has no article')
def stories(context) -> None:
    context.stories = support.story_items()


@when("a page includes a listing of articles with posts as the fallback, three sections, two then one Story each")
def groups(context) -> None:
    context.page = _project(context, "groups", GROUP)


@then("the groups are law, privacy and science")
def group_order(context) -> None:
    assert [name for name, _count, _slugs in support.groups_of(context.page)] == ["law", "privacy", "science"]


@then("law shows its two posts because it has no article")
def law_posts(context) -> None:
    assert support.groups_of(context.page)[0] == ("law", 2, ["p3", "p4"])


@then("every group says how many cards it holds and that its first card is the largest")
def counts(context) -> None:
    assert len(re.findall(r'papyrus-has-lead" data-section="[^"]+" data-label="[^"]*" data-index="\d+" data-count="\d+"', context.page)) == 3


@when('a page includes an article listing for "{section}" with posts as the fallback')
def one_section(context, section: str) -> None:
    context.page = _project(context, "one", f'::include{{kind="listing" type="article" section="{section}" fallback="post" layout="bare"}}')


@then("the block shows the posts of law, best first")
def law_block(context) -> None:
    assert support.slugs(context.page) == ["p3", "p4"]


@then("the block shows the article of privacy and no post")
def privacy_block(context) -> None:
    assert support.slugs(context.page) == ["a1"]


@when("a page includes the groups and then a unique listing of every post")
def groups_then_unique(context) -> None:
    context.page = _project(context, "after", f'{GROUP}\n\n::include{{kind="listing" type="post" count="10" unique="true" layout="bare"}}')


@then("the later listing leaves out every Story the groups showed")
def leaves_out(context) -> None:
    assert support.slugs(context.page.split("</section>")[-1]) == ["p5", "p1", "p2"]


@when("a page includes the groups and then a plain listing of every post")
def groups_then_plain(context) -> None:
    context.page = _project(context, "repeat", f'{GROUP}\n\n::include{{kind="listing" type="post" count="10" layout="bare"}}')


@then("the later listing repeats the posts the groups showed")
def repeats(context) -> None:
    assert support.slugs(context.page.split("</section>")[-1]) == ["p5", "p3", "p1", "p2", "p4"]


@when("a page includes a counted listing of three posts")
def counted(context) -> None:
    context.page = _project(context, "counted", '::include{kind="listing" type="post" count="3" tag="ul" class="rail" counts="true" layout="bare"}')


@then("the wrapper carries the count 3 and the lead class")
def wrapper(context) -> None:
    assert '<ul class="rail papyrus-has-lead" data-count="3">' in context.page


@when("a page includes a listing with sections 2 and a count")
def bad_group(context) -> None:
    site = DirectorySite(settings(pages=[support.page("p")]), [item("x", section="posts")], {"p.md": f'{support.BAND}::include{{kind="listing" sections="2" count="1"}}\n'})
    context.add_cleanup(site.cleanup)
    try:
        site.project_all()
    except ValueError as error:
        context.error = str(error)
    else:
        context.error = None


@then("the projection fails saying a group takes per")
def takes_per(context) -> None:
    assert context.error and "takes per" in context.error, context.error


@given("References, some with a picture and some without")
def with_pictures(context) -> None:
    context.document = support.snapshot(
        support.record("pic", image="/a.png", confidence=0.9), support.record("text", confidence=0.8), support.record("pic2", image="https://x.test/b.png", confidence=0.7)
    )


@when("a page asks for confident References with no picture")
def no_picture(context) -> None:
    context.page = support.drawn({"select": "confident", "image": "none"}, context.document)


@then("only the References without a picture are drawn")
def only_text(context) -> None:
    assert support.keys(context.page) == ["text"]


@given("videos with stars and with predictions")
def videos(context) -> None:
    context.document = support.snapshot(
        support.record("low", medium="video", confidence=0.4, rank=4),
        support.record("starred", medium="video", confidence=0.1, rank=1),
        support.record("sure", medium="video", confidence=0.95, rank=2),
        support.record("paper", confidence=0.99, rank=3),
    )


@when("a page asks for confident videos")
def confident_videos(context) -> None:
    context.page = support.drawn({"select": "confident", "medium": "video"}, context.document)


@then("the starred video is first, then the others by prediction")
def video_order(context) -> None:
    assert support.keys(context.page) == ["starred", "sure", "low"]


@given("accepted References")
def accepted(context) -> None:
    context.document = support.snapshot(support.record("a", confidence=0.9), support.record("b", confidence=0.8))


@when("a page asks for References with an explainer and counts")
def with_explainer(context) -> None:
    context.page = support.drawn({"select": "confident", "counts": "true", "explainer": "How It Works", "explainerBody": "Monitors feed Cyclotrons."}, context.document)


@then("the explainer card is the first item of the grid and is not counted")
def explainer_first(context) -> None:
    grid = context.page.split('<ul class="home-page-grid')[1]
    assert grid.index("home-page-explainer") < grid.index("home-page-tile")
    assert 'data-count="2"' in context.page and support.keys(context.page) == ["a", "b"]
