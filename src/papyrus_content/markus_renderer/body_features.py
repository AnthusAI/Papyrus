"""What a site's pages can contain, as one value that save and publish both read.

A Story body may use the Papyrus vocabulary that is lowered before Markus runs: ``::image{...}``, ``::video{...}`` and the citation markup
(``[@key]``, ``::citations``). Whether a site renders them is a setting of its ``projection.json`` (``images``,
``citations``; both are on unless the site turns them off). ``derive_body`` validates a body at save, and the projector
renders it at publish; both read these features, so a body one accepts the other accepts.

Where the settings live differs by process, so the features come from a provider:

* the content-actions function installs the site projector's features (``MarkusSiteProjector.body_features``);
* the CLI installs the features the site reports (``deriveMarkus`` answers with them), or the local projector's when
  the operator points at a static directory;
* with no provider (a test, an import) the defaults apply: images and citations on, a media store present.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

NO_MEDIA_STORE = (
    "This site has no media store, so a page cannot show an image: ::image needs the site bucket (PAPYRUS_SITE_BUCKET on the "
    "content-actions function) that holds the renditions made when a picture is uploaded."
)
IMAGES_OFF = "This site has turned images off (projection.json \"images\": false), so ::image is not available."
CITATIONS_OFF = "This site has turned citations off (projection.json \"citations\": false), so [@key] and ::citations are not available."


@dataclass(frozen=True)
class BodyFeatures:
    images: bool = True
    citations: bool = True
    #: Why a body with ::image cannot be rendered although images are on (no media store); None when it can.
    images_unavailable: str | None = None
    #: The site declared ``images`` as an object, so its plain Markdown images are made responsive too: every page then
    #: needs the media store, not only a page with ::image.
    plain_images_upgraded: bool = False
    #: ``embeds.enabled`` of the site: a ``::video`` is always accepted, but only a site with embeds on shows a player.
    video_embeds: bool = False

    def to_dict(self) -> dict:
        return {
            "images": self.images,
            "citations": self.citations,
            "imagesUnavailable": self.images_unavailable,
            "plainImagesUpgraded": self.plain_images_upgraded,
            "videoEmbeds": self.video_embeds,
        }

    @classmethod
    def from_dict(cls, value: object) -> "BodyFeatures":
        if not isinstance(value, dict):
            return DEFAULT_FEATURES
        unavailable = value.get("imagesUnavailable")
        return cls(
            images=value.get("images") is not False,
            citations=value.get("citations") is not False,
            images_unavailable=unavailable if isinstance(unavailable, str) and unavailable else None,
            plain_images_upgraded=value.get("plainImagesUpgraded") is True,
            video_embeds=value.get("videoEmbeds") is True,
        )


DEFAULT_FEATURES = BodyFeatures()

_provider: Callable[[], BodyFeatures] | None = None


def install_body_features(provider: Callable[[], BodyFeatures] | BodyFeatures | None) -> None:
    """Install where save reads the site's features from (a value, or a function called at each save); ``None`` removes it."""
    global _provider
    _provider = (lambda: provider) if isinstance(provider, BodyFeatures) else provider


def current_body_features() -> BodyFeatures:
    return _provider() if _provider is not None else DEFAULT_FEATURES
