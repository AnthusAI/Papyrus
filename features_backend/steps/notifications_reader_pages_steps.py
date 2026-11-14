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

from papyrus_content.projection.plugins import PLUGIN_PAGE_PREFIXES, PLUGIN_STATIC_ASSETS  # noqa: E402
from papyrus_content.projection.standard import notifications_pages  # noqa: E402
from procedures.newsroom.tests.notifications_js_support import CONSENT, OFFERED_ONE, OFFERED_TWO, run_component, run_page  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, fixture_settings  # noqa: E402

PAGES_SCRIPT = "_plugins/papyrus-notifications-pages@1.js"
COMPONENT_SCRIPT = "_plugins/papyrus-notifications@1.js"
STATE = "/api/notifications/state"
SUBSCRIBE = "/api/notifications/subscribe"
TOKEN = "tok.en_1-2"
UNAVAILABLE = {"status": 503, "body": {"status": "unavailable"}}
PREFERENCES = {
    "status": 200,
    "body": {
        "status": "ready",
        "email": "reader@example.com",
        "lists": [
            {"id": "stories", "name": "New stories", "description": "Each new story as it is published.", "subscribed": True},
            {"id": "weekly", "name": "Weekly roundup", "description": "", "subscribed": False},
        ],
    },
}


def project(context, plugins, settings=None) -> None:
    kwargs = {"settings": settings, "content": FIXTURES / "sectioned" / "content"} if settings is not None else {}
    context.site = ProjectedSite("sectioned", plugins=plugins, **kwargs) if settings is None else ProjectedSite(plugins=plugins, **kwargs)
    context.add_cleanup(context.site.cleanup)


def main_of(html: str) -> str:
    return html.split('<main id="main">', 1)[1].split("</main>", 1)[0]


def pages(context) -> dict[str, str]:
    return {name: context.site.text(notifications_pages.site_key(name)) for name in notifications_pages.PAGE_NAMES}


@given("a projected site with the notifications plugin enabled")
def enabled(context) -> None:
    project(context, ("notifications",))


@given("a projected site with no notifications plugin")
def disabled(context) -> None:
    project(context, ())


@given('a projected site under the base path "{base}" with the notifications plugin enabled')
def based(context, base: str) -> None:
    settings = fixture_settings("sectioned")
    settings["urls"] = {**settings.get("urls", {}), "basePath": base}
    settings.pop("images", None)
    settings.pop("media", None)
    project(context, ("notifications",), settings)


@then('the site has the notifications pages {names}')
def has_pages(context, names: str) -> None:
    for name in re.findall(r'"([a-z]+)"', names):
        assert notifications_pages.site_key(name) in context.site.tree, name


@then('the subscribe page is at "{key}"')
def subscribe_key(context, key: str) -> None:
    assert notifications_pages.site_key("index") == key and key in context.site.tree


# 'the site has no page under "<prefix>"' is defined in alexa_privacy_pages_steps.py and works on context.site.


@then("the site has no notifications scripts")
def no_scripts(context) -> None:
    assert PAGES_SCRIPT not in context.site.tree and COMPONENT_SCRIPT not in context.site.tree


@then("every notifications page has the site's header, stylesheet and footer")
def chrome(context) -> None:
    for name, html in pages(context).items():
        assert "<header" in html and "<footer" in html and 'rel="stylesheet"' in html, name
        assert re.search(r'<main id="main">\s*<div class="markus-document markus-notifications-page"', html), name


@then("every notifications page is noindex and sends the same-origin referrer")
def noindex(context) -> None:
    for name, html in pages(context).items():
        assert '<meta name="robots" content="noindex, nofollow">' in html, name
        assert '<meta name="referrer" content="same-origin">' in html, name


@then("no notifications page is in the sitemap, the feeds, llms.txt or a Markdown twin")
def unlisted(context) -> None:
    tree = context.site.tree
    listed = "".join(context.site.text(key) for key in tree if key.startswith("sitemap"))
    listed += "".join(context.site.text(key) for key in ("llms.txt", "llms-full.txt", "feed.xml", "atom.xml"))
    assert "notifications" not in listed
    assert not [key for key in tree if key.startswith("notifications/") and key.endswith(".md")]


@then('no notifications page links to an "{fragment}" address')
def no_api_links(context, fragment: str) -> None:
    for name, html in pages(context).items():
        assert not re.findall(rf'href="[^"]*{re.escape(fragment)}', html), name


@then("every notifications page loads its scripts from external files and has no inline script or style")
def strict_csp(context) -> None:
    baseline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>.*?</script>", context.site.text("404.html"), re.S)
    for name, html in pages(context).items():
        assert PAGES_SCRIPT in html, name
        assert re.findall(r"<script(?![^>]*\bsrc=)[^>]*>.*?</script>", html, re.S) == baseline, name
        assert " style=" not in html.split("<body", 1)[1], name


@then("only the subscribe page loads the web component")
def component_only_on_subscribe(context) -> None:
    for name, html in pages(context).items():
        assert (COMPONENT_SCRIPT in html) == (name == "index"), name


@then("no notifications page has a dropdown")
def no_dropdowns(context) -> None:
    for name, html in pages(context).items():
        assert "<select" not in html and "<option" not in html, name


@then("every notifications button carries a Lucide icon")
def lucide(context) -> None:
    for name, html in pages(context).items():
        for button in re.findall(r"<button .*?</button>", main_of(html), re.S):
            assert 'data-icon="' in button, (name, button)


@then("the notifications stylesheet rules draw no borders")
def flat(context) -> None:
    rules = [line for line in context.site.text("css/markus-components.css").splitlines() if "notifications" in line]
    assert rules
    values = {value.strip() for line in rules for value in re.findall(r"(?<![\w-])border(?:-(?!radius)[a-z-]+)?\s*:\s*([^;]+)", line)}
    assert values <= {"0", "none"}, values


# ---- subscribing (the web component, run against a fake network)

@given("a site with notifications on that offers one list")
def one_list(context) -> None:
    context.offered = OFFERED_ONE
    context.subscribe_reply = {"status": 202, "body": {"status": "check_email"}}


@given("a site with notifications on that offers two lists")
def two_lists(context) -> None:
    context.offered = OFFERED_TWO
    context.subscribe_reply = {"status": 202, "body": {"status": "check_email"}}


def subscribe(context, before: str = "") -> None:
    context.outcome = run_component(
        {STATE: context.offered, SUBSCRIBE: context.subscribe_reply},
        f"""const el = mount({{}}); await settle();
        byClass(el, "markus-notifications-input")[0].value = "reader@example.com";
        {before}
        await el.queryAll("form")[0].listeners.submit({{ preventDefault() {{}} }}); await settle();
        const states = byClass(el, "markus-notifications-toggle").map((b) => b.queryAll(".markus-notifications-state")[0].textContent);
        console.log(JSON.stringify({{ status: byClass(el, "markus-notifications-status")[0].textContent,
          posts: requests.filter((r) => r.method === "POST").map((r) => r.url), states,
          bodies: requests.filter((r) => r.method === "POST").map((r) => r.body),
          consent: byClass(el, "markus-notifications-consent")[0].textContent }}));""",
    )


@when("a reader opens its notifications page and enters an address")
def opens_and_enters(context) -> None:
    project(context, ("notifications",))
    html = context.site.text(notifications_pages.site_key("index"))
    assert "<papyrus-notifications></papyrus-notifications>" in html, "the page places the component"
    context.subscribe_page = html
    if context.offered is OFFERED_ONE:
        subscribe(context)


@then("the page says to check their email, in the site's own design")
def check_email(context) -> None:
    assert context.outcome["status"] == "Check your email to confirm your subscription."
    html = context.subscribe_page
    assert "<header" in html and "<footer" in html and "/css/site-theme.css" in html


@then("the subscription request goes to the site's own subscribe address and not to a page address")
def request_address(context) -> None:
    assert context.outcome["posts"] == [SUBSCRIBE]


@then("each list is a button that says Off until it is pressed")
def lists_start_off(context) -> None:
    subscribe(context)
    assert context.outcome["states"] == ["Off", "Off"]


@then("pressing Subscribe without choosing a list asks them to choose at least one")
def must_choose(context) -> None:
    assert context.outcome["status"] == "Choose at least one thing to get."
    assert context.outcome["posts"] == []


@then("the form shows exactly the site's consent wording")
def shows_consent(context) -> None:
    assert context.outcome["consent"] == CONSENT


@then("the subscription request carries that wording")
def carries_consent(context) -> None:
    assert context.outcome["bodies"][0]["consent"] == CONSENT


@when("the service answers that the reader's network should slow down")
def slow_down(context) -> None:
    context.subscribe_reply = {"status": 429, "body": {"status": "slow_down"}}
    project(context, ("notifications",))
    subscribe(context)


@then("the subscribe page says in words to try again later")
def says_slow_down(context) -> None:
    assert context.outcome["status"] == "Too many signups from your network just now. Please try again later."


@when("the service answers that notifications are not available")
def service_down(context) -> None:
    context.subscribe_reply = UNAVAILABLE
    context.preferences_reply = UNAVAILABLE
    if getattr(context, "offered", None) is not None:
        project(context, ("notifications",))
        subscribe(context)
    else:
        open_manage(context)


@then("the subscribe page says in words that notifications are not available right now")
def subscribe_unavailable(context) -> None:
    assert context.outcome["status"] == "Notifications are not available right now. Please try again later."


# ---- managing (the pages script, run against the projected markup)

@given("a confirmed subscriber follows the manage link")
def follows_manage_link(context) -> None:
    context.offered = None
    project(context, ("notifications",))
    context.preferences_reply = PREFERENCES
    context.search = f"?token={TOKEN}"


def open_manage(context, search: str | None = None, body: str = "") -> None:
    context.outcome = run_page(
        context.site.text(notifications_pages.site_key("preferences")),
        search if search is not None else context.search,
        {STATE: context.preferences_reply},
        body
        or """console.log(JSON.stringify({ replaced, unavailable: visible("[data-notifications-unavailable]"), form: visible("form") }));""",
    )


@when("they turn new-story email off and save")
def turns_off(context) -> None:
    saved = json.loads(json.dumps(PREFERENCES))
    saved["body"]["lists"][0]["subscribed"] = False
    # The reader presses the button, the form posts, and the site redirects back with msg=saved: the page then reads the new state.
    context.preferences_reply = saved
    context.search = f"?token={TOKEN}&msg=saved"
    open_manage(
        context,
        body="""console.log(JSON.stringify({
          rows: $("form").queryAll("button.markus-notifications-toggle").map((b) => [b.queryAll(".markus-notifications-name")[0].textContent, b.queryAll(".markus-notifications-state")[0].textContent,
            /data-icon="([a-z-]+)"/.exec(b.queryAll(".markus-notifications-mark")[0].innerHTML)[1]]),
          notice: text("[data-notifications-notice] span") }));""",
    )


@then("each list on the page says On or Off in words and with a bell mark")
def words_and_marks(context) -> None:
    assert context.outcome["rows"] == [["New stories", "Off", "bell-off"], ["Weekly roundup", "Off", "bell-off"]]


@then("the page confirms in words that the new-story email is off")
def confirms_in_words(context) -> None:
    assert context.outcome["notice"].startswith("Your choices are saved."), context.outcome
    assert "New stories" not in context.outcome["notice"].split("You get:")[-1] or "You get nothing" in context.outcome["notice"]


@when("someone opens a manage link that is no good")
def bad_link(context) -> None:
    project(context, ("notifications",))
    context.preferences_reply = {"status": 400, "body": {"status": "invalid"}}
    open_manage(context, f"?token={TOKEN}")


@then("they land on the site's expired page, not an /api address")
def expired(context) -> None:
    assert context.outcome["replaced"] == "/notifications/expired/"
    assert "/api" not in context.outcome["replaced"]
    assert "This link did not work" in context.site.text(notifications_pages.site_key("expired"))


@then("the page says in words that notifications are not available right now")
def manage_unavailable(context) -> None:
    assert context.outcome["unavailable"] is True and context.outcome["form"] is False
    assert "Notifications are not available right now." in context.site.text(notifications_pages.site_key("preferences"))


@then("the reader is not sent to the expired page")
def not_expired(context) -> None:
    assert context.outcome["replaced"] is None


@when("they ask to delete their data")
def asks_delete(context) -> None:
    context.search = f"?token={TOKEN}&step=delete"
    open_manage(
        context,
        body="""console.log(JSON.stringify({ confirm: visible("[data-notifications-section=delete]"), manage: visible("[data-notifications-section=manage]"),
          back: $("[data-notifications-back]").href }));""",
    )


@then("the page asks them to confirm and offers a way back")
def delete_confirm(context) -> None:
    assert context.outcome["confirm"] and not context.outcome["manage"]
    assert context.outcome["back"] == f"/notifications/preferences/?token={TOKEN}"


@then('the expired page links back to "{href}"')
def expired_links_back(context, href: str) -> None:
    key = next(key for key in context.site.tree if key.endswith("notifications/expired/index.html"))
    assert f'href="{href}"' in context.site.text(key)


@then("the projector owns every notifications page")
def owns(context) -> None:
    assert all(context.site.projector.owns_page_key(notifications_pages.site_key(name)) for name in notifications_pages.PAGE_NAMES)


@then('a reconcile treats "{prefix}" as a plugin page prefix')
def prefix(context, prefix: str) -> None:
    assert PLUGIN_PAGE_PREFIXES["notifications"] == (prefix,)
    assert "notifications" in PLUGIN_STATIC_ASSETS
