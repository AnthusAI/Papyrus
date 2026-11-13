"""The serving part of the languages setting and slug drafting (features_backend/language-serving-settings.feature). Pure functions; no network."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.language_serving import SLUG_MAX_BYTES, EmptySlug, localized_slug, serving_languages, unique_slug  # noqa: E402
from papyrus_content.url_paths import encoded_path  # noqa: E402


@given('the languages setting enables "{tags}" with "{primary}" as the primary')
def step_setting(context, tags, primary):
    context.languages = {"primary": primary, "enabled": [tag.strip() for tag in tags.split(",")]}


@given('the public languages are set to "{tags}"')
def step_public(context, tags):
    context.languages["public"] = [tag.strip() for tag in tags.split(",")]


@when("the serving languages are read")
def step_read(context):
    try:
        context.serving, context.refusal = serving_languages({"languages": context.languages}), None
    except ValueError as error:
        context.serving, context.refusal = None, str(error)


@then('"es-419" is served under "es" and "zh-Hans" under "zh", and "en" at the root')
def step_prefixes(context):
    assert dict(context.serving.prefixes) == {"en": "", "es-419": "es", "zh-Hans": "zh"}, context.serving.prefixes


@then('the public languages are "{tags}"')
def step_public_read(context, tags):
    assert context.serving.public == tuple(tag.strip() for tag in tags.split(","))


@then('the setting is refused naming "{text}"')
def step_refused(context, text):
    assert context.refusal and text in context.refusal, context.refusal


@then('the slug policy of "{first}" is "{first_policy}" and of "{second}" is "{second_policy}"')
def step_policies(context, first, first_policy, second, second_policy):
    assert context.serving.slugs[first] == first_policy and context.serving.slugs[second] == second_policy, context.serving.slugs


def _draft(context, title, policy, **keywords):
    try:
        context.slug, context.slug_refusal = localized_slug(title, policy, primary_slug=keywords.pop("primary_slug", "the-original"), **keywords), None
    except EmptySlug as error:
        context.slug, context.slug_refusal = None, str(error)


@when('a slug is drafted from a Chinese title of {count:d} characters with the policy "{policy}"')
def step_draft_long(context, count, policy):
    context.long_title = ("能泄露你住在哪里的声音" * 10)[:count]
    _draft(context, context.long_title, policy)


@when('a slug is drafted from "{title}" with the policy "primary" and the original slug "{slug}"')
def step_draft_primary(context, title, slug):
    _draft(context, title, "primary", primary_slug=slug)


@when('a slug is drafted from "{title}" with the policy "pinyin" and the romanizer "{romanized}"')
def step_draft_pinyin(context, title, romanized):
    _draft(context, title, "pinyin", romanize=lambda text: romanized)


@when('a slug is drafted from "{title}" with the policy "{policy}"')
def step_draft(context, title, policy):
    _draft(context, title, policy)


@then('the slug is "{slug}"')
def step_slug(context, slug):
    assert context.slug == slug, context.slug


@then("the slug is its first 85 characters, 255 bytes of UTF-8, the most a directory name holds")
def step_long(context):
    assert context.slug == context.long_title[:85] and len(context.slug.encode("utf-8")) == SLUG_MAX_BYTES == 255


@then("the longest Chinese page address stays within an S3 key and a CloudFront request line once percent-encoded")
def step_limits(context):
    key = f"zh/concepts/{context.slug}/index.html"
    url = encoded_path("/" + key)
    assert len(key.encode("utf-8")) <= 1024            # an S3 object key is at most 1,024 bytes of UTF-8
    assert len(url) <= 8192                             # CloudFront's request line (URL and query) is at most 8,192 bytes
    assert len(encoded_path(f"/zh/concepts/{context.slug}/")) > 512   # recorded, not hidden: above a KeyValueStore key (redirects only)


@then("the slug is the whole title")
def step_whole(context):
    assert context.slug == context.long_title


@then("the drafting is refused and asks for a slug to be given")
def step_empty(context):
    assert context.slug is None and "give this localization a slug" in context.slug_refusal


@given('the Chinese Stories already use "{first}" and "{second}"')
def step_taken(context, first, second):
    context.taken = {first, second}


@when('the slug "{slug}" is made unique within Chinese')
def step_unique(context, slug):
    context.slug = unique_slug(slug, lambda candidate: candidate in context.taken)
