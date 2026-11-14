"""The shape of a post: the link with its UTM tags and the length as X counts it.

X's rule (twitter-text, the library X publishes): a post may weigh at most 280. Most Latin characters weigh 1 and most other characters (CJK, emoji) weigh 2;
every link weighs 23 whatever its length, because X wraps it. Text is counted in Unicode NFC. No link shortener is used, and no picture is uploaded: X builds
the link card from the page's share tags.

Emoji sequences are counted one code point at a time, which can only overcount: a post that fits here fits at X.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAXIMUM_WEIGHT = 280
LINK_WEIGHT = 23
#: Code point ranges that weigh 1 (twitter-text configuration v3); everything else weighs 2.
LIGHT_RANGES = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
UTM = (("utm_source", "x"), ("utm_medium", "social"), ("utm_campaign", "announcement"))
LINK = re.compile(r"https?://[^\s<>\"']+")
SEPARATOR = "\n\n"


def tagged_link(url: str) -> str:
    """The Story's address with the announcement UTM tags added (existing query parameters are kept, existing UTM tags are replaced)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"A post links to a web address, not {url!r}.")
    kept = [(name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True) if name not in dict(UTM)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept + list(UTM)), ""))


def _weight_of(character: str) -> int:
    code = ord(character)
    return 1 if any(low <= code <= high for low, high in LIGHT_RANGES) else 2


def weighted_length(text: str) -> int:
    """The post's weight as X counts it: links 23 each, other characters 1 or 2."""
    text = unicodedata.normalize("NFC", text)
    total, position = 0, 0
    for found in LINK.finditer(text):
        total += sum(_weight_of(character) for character in text[position : found.start()]) + LINK_WEIGHT
        position = found.end()
    return total + sum(_weight_of(character) for character in text[position:])


def compose(draft: str, link: str) -> str:
    """The post exactly as sent: the drafted line, a blank line, the tagged link."""
    return f"{draft.strip()}{SEPARATOR}{link}"


def too_long_by(post: str) -> int:
    return max(0, weighted_length(post) - MAXIMUM_WEIGHT)


def live_markup(draft: str, story_text: str) -> list[str]:
    """Mentions, hashtags and cashtags in the draft that the Story's own text does not have: X would turn them into live links, so the draft may not invent them."""
    return sorted({found for found in re.findall(r"(?<![\w])(?:[@#]\w+|\$[A-Za-z]+)", draft) if found.lower() not in story_text.lower()})
