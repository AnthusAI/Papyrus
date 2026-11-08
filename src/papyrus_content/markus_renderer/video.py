"""``::video{...}``: a playable video in a Story, written like ``::image{...}`` (docs/markus-content-markup.md, "Videos").

A video is a click-to-play poster, never an always-loaded frame. The page holds a poster (a picture in the site's own storage) and a real
``<button>``; only a click swaps in the provider's player (``papyrus-video-v1.js``). Nothing in the static HTML makes a request to the provider:
the only provider addresses on the page are the plain link and the player address kept in a ``data-`` attribute for the script.

Providers are data. ``REGISTRY`` below is the one list of the providers Papyrus knows: how to recognise an address, how to name the video, the
plain address, the player address, whether the provider has a thumbnail we may copy, and the origin the site's Content-Security-Policy must
allow. A site chooses which providers play with ``embeds.providers`` (empty by default: the feature is then not there at all).

This module is the pure part: reading the attributes (``parse_video``), the registry, and the HTML (``render_video`` / ``render_plain``).
Nothing here reads the site's storage or settings; the projector hands in the poster markup it found (or ``None``) and the site's ``VideoRendering``.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass
from types import MappingProxyType

from ..youtube_transcript import YOUTUBE_HOSTS, video_id as youtube_video_id


@dataclass(frozen=True)
class Provider:
    """One video provider, as data."""

    name: str
    label: str
    hosts: frozenset[str]
    #: ``(path regex, id group)`` pairs tried against the address path; YouTube also has its own parser (its ids live in a query too).
    path_patterns: tuple[str, ...]
    #: The plain address of a video (``{id}``), and how a start time is written onto it.
    watch: str
    watch_start: str
    #: The player address (``{id}``) the script creates on a click, its fixed query, and how a start time is written onto it.
    embed: str
    embed_query: tuple[tuple[str, str], ...]
    embed_start: str
    #: ``True`` when a thumbnail can be fetched and copied (``papyrus stories capture-video-posters``); ``False`` means the author gives ``poster=``.
    thumbnail: bool
    #: ``aspect-ratio`` of the player when it is not the design system's media ratio (a portrait post, for instance).
    ratio: str | None = None
    address_shapes: str = ""

    @property
    def frame_origin(self) -> str:
        parts = urllib.parse.urlsplit(self.embed)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def embed_prefix(self) -> str:
        """The only start of a frame address the player script accepts for this provider."""
        return self.embed.split("{id}")[0]

    @property
    def start_supported(self) -> bool:
        return bool(self.watch_start or self.embed_start)


#: Everything Papyrus knows about video providers. Adding a provider is adding a row here (and its origin to the script's list, which a test compares).
REGISTRY: "MappingProxyType[str, Provider]" = MappingProxyType({
    "youtube": Provider(
        name="youtube", label="YouTube", hosts=frozenset({*YOUTUBE_HOSTS, "youtu.be"}), path_patterns=(),
        watch="https://www.youtube.com/watch?v={id}", watch_start="&t={start}s",
        embed="https://www.youtube-nocookie.com/embed/{id}", embed_query=(("autoplay", "1"), ("rel", "0")), embed_start="query:start",
        thumbnail=True,
        address_shapes="https://www.youtube.com/watch?v=ID, https://youtu.be/ID, https://www.youtube.com/shorts/ID, https://www.youtube.com/live/ID or https://www.youtube.com/embed/ID",
    ),
    "vimeo": Provider(
        name="vimeo", label="Vimeo", hosts=frozenset({"vimeo.com", "www.vimeo.com", "player.vimeo.com"}),
        path_patterns=(r"^/(?:video/|channels/[\w-]+/|groups/[\w-]+/videos/|album/\d+/video/)?(?P<id>\d{4,12})/?$",),
        watch="https://vimeo.com/{id}", watch_start="#t={start}s",
        embed="https://player.vimeo.com/video/{id}", embed_query=(("autoplay", "1"), ("dnt", "1")), embed_start="fragment:t={start}s",
        thumbnail=True,
        address_shapes="https://vimeo.com/ID or https://player.vimeo.com/video/ID",
    ),
    "instagram": Provider(
        name="instagram", label="Instagram", hosts=frozenset({"instagram.com", "www.instagram.com"}),
        path_patterns=(r"^/(?:[\w.]+/)?(?:p|reel|reels|tv)/(?P<id>[\w-]{5,30})/?$",),
        watch="https://www.instagram.com/p/{id}/", watch_start="",
        embed="https://www.instagram.com/p/{id}/embed/", embed_query=(), embed_start="",
        thumbnail=False, ratio="4 / 5",
        address_shapes="https://www.instagram.com/p/ID/, https://www.instagram.com/reel/ID/ or https://www.instagram.com/tv/ID/",
    ),
})
#: The provider names, in the order the registry lists them: what ``embeds.providers`` may name.
PROVIDERS = tuple(REGISTRY)
PROVIDER_WORDS = ", ".join(provider.label for provider in REGISTRY.values())
ALLOWED_ATTRIBUTES = ("src", "title", "caption", "credit", "start", "layout", "poster")
LAYOUTS = ("inline", "full")
DEFAULT_LAYOUT = "inline"

#: The poster of a video with a fetchable thumbnail is our own copy, in the site's media storage; this is where ``papyrus stories capture-video-posters`` puts it.
POSTER_DIRECTORY = "assets/video-posters"
#: A poster the author names must be a plain image path in the site's own storage: no address, no ``..``.
POSTER_ATTRIBUTE = re.compile(r"^/?[\w][\w./-]*\.(?:jpg|jpeg|png|webp|avif)$", re.I)

SCRIPT_PATH = "_plugins/papyrus-video-v1.js"

#: Lucide ``play`` (lucide.dev, ISC licence), drawn as a flat filled shape in the button's own colour.
PLAY_ICON = (
    '<svg class="papyrus-video-icon" xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="currentColor" '
    'stroke="none" aria-hidden="true" focusable="false" data-icon="play"><path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/></svg>'
)

#: Stock rules, emitted once per page by the first video. Colours come from the site's own tokens with a flat fallback; no outlines, no hairlines.
#: The ratio is the design system's media ratio token. Without the script the button stays hidden and the poster is a link.
STYLE = (
    ".papyrus-video-player{position:relative;overflow:hidden;aspect-ratio:var(--papyrus-media-ratio,16 / 9);"
    "border-radius:var(--papyrus-radius,.5rem);background:var(--papyrus-media-bg,color-mix(in srgb,currentColor 12%,transparent))}"
    ".papyrus-video-link{position:absolute;inset:0;display:block;color:inherit;text-decoration:none}"
    ".papyrus-video-poster,.papyrus-video-poster picture{display:block;width:100%;height:100%}"
    ".papyrus-video-poster img{display:block;width:100%;height:100%;object-fit:cover}"
    ".papyrus-video-title{position:absolute;left:0;right:0;bottom:0;padding:.75rem 1rem;font-weight:600;"
    "background:var(--papyrus-media-scrim,rgba(0,0,0,.72));color:var(--papyrus-media-scrim-ink,#fff)}"
    ".papyrus-video-play{display:none;position:absolute;inset:0;width:100%;height:100%;margin:0;padding:0;border:0;border-radius:inherit;"
    "background:transparent;color:var(--papyrus-media-play-ink,#fff);cursor:pointer;align-items:center;justify-content:center}"
    ".papyrus-video-play::before{content:\"\";position:absolute;width:4.5rem;height:4.5rem;border-radius:50%;"
    "background:var(--papyrus-media-play-bg,rgba(0,0,0,.72))}"
    ".papyrus-video-play .papyrus-video-icon{position:relative;width:1.75rem;height:1.75rem;margin-left:.2rem}"
    ".papyrus-video-play:hover::before,.papyrus-video-play:focus-visible::before{background:var(--papyrus-media-play-hover,rgba(0,0,0,.88))}"
    ".papyrus-video-play:focus-visible{outline:3px solid var(--papyrus-focus,currentColor);outline-offset:-3px}"
    ".papyrus-video-player.is-ready .papyrus-video-play{display:flex}"
    ".papyrus-video-player.is-ready .papyrus-video-link{display:none}"
    ".papyrus-video-player iframe{position:absolute;inset:0;width:100%;height:100%;border:0}"
    ".papyrus-video-placeholder{display:block;width:100%;height:100%}"
    "@media (prefers-color-scheme:dark){.papyrus-video-player{background:var(--papyrus-media-bg,color-mix(in srgb,currentColor 18%,transparent))}}"
)



#: A provider whose player is not the media ratio (a portrait post) says so in the registry; its rule is added here so the registry stays the one list.
STYLE += "".join(
    f'.papyrus-video-player[data-provider="{spec.name}"]{{aspect-ratio:{spec.ratio}}}' for spec in REGISTRY.values() if spec.ratio
)


@dataclass(frozen=True)
class VideoRequest:
    """One ``::video{...}`` as written."""

    src: str
    video_id: str
    title: str
    credit: str
    caption: str | None = None
    start: int | None = None
    layout: str = DEFAULT_LAYOUT
    provider: str = "youtube"
    poster: str | None = None

    @property
    def spec(self) -> Provider:
        return REGISTRY[self.provider]

    @property
    def watch_url(self) -> str:
        """The plain address of the video on the provider (every address shape written the same way), with the start time when there is one."""
        spec = self.spec
        suffix = spec.watch_start.format(start=self.start) if self.start and spec.watch_start else ""
        return spec.watch.format(id=self.video_id) + suffix

    @property
    def poster_source(self) -> str:
        """The site storage path of the poster: the author's ``poster=`` (without its leading slash) or ``assets/video-posters/<provider>-<id>.jpg``."""
        return self.poster.lstrip("/") if self.poster else poster_source(self.provider, self.video_id)

    @property
    def has_poster_source(self) -> bool:
        """Whether the page can know where its poster is: the author named one, or the provider has a thumbnail we copy."""
        return bool(self.poster) or self.spec.thumbnail

    @property
    def embed_url(self) -> str:
        """The player address the script creates on a click."""
        spec = self.spec
        query = dict(spec.embed_query)
        address = spec.embed.format(id=self.video_id)
        fragment = ""
        if self.start and spec.embed_start.startswith("query:"):
            query[spec.embed_start.split(":", 1)[1]] = str(self.start)
        if self.start and spec.embed_start.startswith("fragment:"):
            fragment = "#" + spec.embed_start.split(":", 1)[1].format(start=self.start)
        return address + (f"?{urllib.parse.urlencode(query)}" if query else "") + fragment


@dataclass(frozen=True)
class VideoRendering:
    """What a site lets a video be (``projection.json`` ``embeds``): the providers that play. Empty (the default): core does not read ``::video`` at all, so it reaches any site hook as before."""

    providers: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    @property
    def frame_origins(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(REGISTRY[name].frame_origin for name in self.providers if name in REGISTRY))


def poster_source(provider: str, identifier: str) -> str:
    return f"{POSTER_DIRECTORY}/{provider}-{identifier}.jpg"


def provider_of(address: str) -> str | None:
    """The registered provider an address belongs to (by its host), or ``None``. Any other ``::video`` address is a site's own business."""
    try:
        parts = urllib.parse.urlsplit((address or "").strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    return next((name for name, spec in REGISTRY.items() if host in spec.hosts), None)


def _id_in(spec: Provider, value: str) -> str | None:
    if spec.name == "youtube":
        return youtube_video_id(value)
    path = urllib.parse.urlsplit(value).path
    for pattern in spec.path_patterns:
        found = re.match(pattern, path)
        if found:
            return found.group("id")
    return None


def parse_address(address: str) -> tuple[str, str]:
    """``(provider, video id)`` of an address, with the plain-words error naming the allowed providers for anything else."""
    value = (address or "").strip()
    name = provider_of(value)
    if name is None:
        raise ValueError(f"src {value!r} is not an address of a supported video provider. Allowed providers: {PROVIDER_WORDS}.")
    spec = REGISTRY[name]
    found = _id_in(spec, value)
    if found is None:
        raise ValueError(f"src {value!r} is a {spec.label} address without a video in it. Use {spec.address_shapes}.")
    return name, found


def video_id_of(address: str) -> str:
    """The video id of a supported address (``ValueError`` as ``parse_address``)."""
    return parse_address(address)[1]


def parse_video(attributes: dict[str, str], written: str = "") -> VideoRequest:
    """Check the attributes of a ``::video{...}`` whose address is a registered provider's; ``ValueError`` names what to change."""
    where = "::video{...}"
    unknown = set(attributes) - set(ALLOWED_ATTRIBUTES)
    if unknown:
        raise ValueError(f"{where} got unknown attribute(s) {', '.join(sorted(unknown))}. Allowed: {', '.join(ALLOWED_ATTRIBUTES)}.")
    src = (attributes.get("src") or "").strip()
    if not src:
        raise ValueError(f"{where} needs a src attribute: the address of a video ({PROVIDER_WORDS}): {written.strip()!r}")
    try:
        provider, identifier = parse_address(src)
    except ValueError as error:
        raise ValueError(f"{where} {error}") from None
    spec = REGISTRY[provider]
    title = " ".join((attributes.get("title") or "").split())
    if not title:
        raise ValueError(f'{where} needs a title attribute: the accessible name of the player, for example title="Aircraft sound localisation demonstration".')
    credit = " ".join((attributes.get("credit") or "").split())
    if not credit:
        raise ValueError(f'{where} needs a credit attribute: the channel or person who made the video, for example credit="Example Channel". Third-party media is always credited.')
    start = None
    if attributes.get("start") not in (None, ""):
        raw = attributes["start"].strip()
        if not re.fullmatch(r"\d{1,6}", raw):
            raise ValueError(f'{where} start must be whole seconds such as start="90", not {raw!r}.')
        if not spec.start_supported:
            raise ValueError(f"{where} start is not supported for {spec.label} videos.")
        start = int(raw)
    layout = (attributes.get("layout") or DEFAULT_LAYOUT).strip()
    if layout not in LAYOUTS:
        raise ValueError(f'{where} layout must be one of {", ".join(LAYOUTS)}, not {layout!r}.')
    poster = (attributes.get("poster") or "").strip() or None
    if poster is not None and (".." in poster or not POSTER_ATTRIBUTE.match(poster)):
        raise ValueError(f'{where} poster must be the path of a picture in the site\'s own storage such as poster="/assets/reel-poster.jpg", not {poster!r}.')
    caption = " ".join((attributes.get("caption") or "").split()) or None
    return VideoRequest(src=src, video_id=identifier, title=title, credit=credit, caption=caption, start=start, layout=layout, provider=provider, poster=poster)


def _q(value: object) -> str:
    return html.escape(str(value), quote=True)


def _caption(request: VideoRequest) -> str:
    watch = _q(request.watch_url)
    bits = [_q(request.caption)] if request.caption else []
    bits.append(f'<span class="papyrus-image-credit"><a href="{watch}" rel="noopener noreferrer">{_q(request.credit)}</a></span>')
    return f'<figcaption>{" · ".join(bits)}</figcaption>'


def render_plain(request: VideoRequest) -> str:
    """The plain linked credit line a site with embeds on shows for a video whose provider it has not listed: no player, no picture, no script.

    ``Video: <title linked to the video>. <caption>. Credit: <credit>.``"""
    watch = _q(request.watch_url)
    bits = [f'Video: <a href="{watch}" rel="noopener noreferrer">{_q(request.title)}</a>.']
    if request.caption:
        bits.append(f"{_q(request.caption)}")
    bits.append(f"Credit: {_q(request.credit)}.")
    return f'<p class="papyrus-video-line">{" ".join(bits)}</p>'


def render_video(
    request: VideoRequest,
    rendering: VideoRendering,
    *,
    poster: str | None = None,
    classes: str = "",
    with_style: bool = True,
) -> str:
    """The figure for one video (only called for a provider the site lists in ``embeds.providers``).

    ``poster`` is the finished markup of our own copy of the thumbnail (a ``<picture>`` or ``<img>``), or ``None`` when the copy is missing, which
    shows a flat placeholder with the title: never a broken image and never an address on the provider. ``classes`` are the figure's classes (the
    image layout classes plus ``papyrus-video``).
    """
    watch = _q(request.watch_url)
    caption = _caption(request)
    figure_classes = _q(" ".join(part for part in (classes, "papyrus-video") if part))
    surface = poster if poster else '<span class="papyrus-video-placeholder" aria-hidden="true"></span>'
    style = f"<style>{STYLE}</style>" if with_style else ""
    return (
        f"{style}<figure class=\"{figure_classes}\">"
        f'<div class="papyrus-video-player" data-papyrus-video="" data-provider="{_q(request.provider)}" data-embed="{_q(request.embed_url)}" '
        f'data-title="{_q(request.title)}">'
        f'<a class="papyrus-video-link" href="{watch}" rel="noopener noreferrer">'
        f'<span class="papyrus-video-poster">{surface}</span><span class="papyrus-video-title">{_q(request.title)}</span></a>'
        f'<button type="button" class="papyrus-video-play" aria-label="{_q(request.title)}">{PLAY_ICON}</button>'
        f"</div>{caption}</figure>"
    )


def csp_directives(rendering: VideoRendering) -> dict[str, tuple[str, ...]]:
    """The Content-Security-Policy directives a site with these ``embeds`` needs, and nothing more: ``frame-src`` for the player's origin. None when embeds are off."""
    if not rendering.enabled or not rendering.frame_origins:
        return {}
    return {"frame-src": rendering.frame_origins}


def csp_text(rendering: VideoRendering) -> str:
    """The same as one policy fragment: ``frame-src https://www.youtube-nocookie.com`` (empty when embeds are off)."""
    return "; ".join(f"{name} {' '.join(sources)}" for name, sources in csp_directives(rendering).items())
