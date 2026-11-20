"""The generation handlers on the signed-in lane: the person's own session reads and writes the backend, and spending still needs the site's approval.

Each call opens the signed-in person's authoring client and builds the real store (``ItemCandidateStore``) and the real apply writer (``StoryMediaWriter``)
over it; the provider named by the site's settings is made at that moment and reads its key only when a picture is requested. ``Generation`` refuses before
any of that is used unless the site's image guidelines configure a model and approve spending. Tests pass fakes for every part.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from .candidate_store import ItemCandidateStore
from .generation import Generation
from .handlers import Caller, Handler, Outcome
from .profile_handlers import identify
from .providers import ImageProvider, openai_from_environment
from .story_media import StoryMediaWriter, s3_put_object

OPERATION_METHODS = {"image_capabilities": "capabilities", "image_generate": "generate", "image_round_get": "round_get", "image_discard": "discard", "image_apply": "apply"}


def _default_client():
    from papyrus_content.graphql_authoring import create_authoring_client

    return create_authoring_client()[0]


def _default_providers() -> dict[str, ImageProvider]:
    return {"openai": openai_from_environment()}


def _default_writer(client: Any) -> StoryMediaWriter:
    from papyrus_content.story_images import open_media_store

    return StoryMediaWriter(client, s3_put_object(open_media_store()))


def signed_in_generation_handlers(client_factory: Callable[[], Any] | None = None, providers: Callable[[], dict[str, ImageProvider]] | None = None,
                                  store_factory: Callable[[Any], Any] | None = None, writer_factory: Callable[[Any], Any] | None = None) -> dict[str, Handler]:
    def build(client: Any) -> Generation:
        store = store_factory(client) if store_factory else ItemCandidateStore(client)
        writer = writer_factory(client) if writer_factory else _LazyWriter(client)
        return Generation(client, store, (providers or _default_providers)(), media=writer, stories=writer)

    def wrap(method: str) -> Handler:
        def handler(arguments: dict, caller: Caller) -> Outcome:
            client = (client_factory or _default_client)()
            return getattr(build(client), method)(arguments, identify(client, caller))
        return handler

    return {name: wrap(method) for name, method in OPERATION_METHODS.items()}


class _LazyWriter:
    """Opens the media store only when apply actually writes a picture, so reading, generating and discarding never need S3 rights."""
    def __init__(self, client: Any):
        self.client, self.writer = client, None

    def _writer(self) -> StoryMediaWriter:
        if self.writer is None:
            self.writer = _default_writer(self.client)
        return self.writer

    def add_media(self, **fields: Any) -> dict:
        return self._writer().add_media(**fields)

    def open_review_request(self, **fields: Any) -> str:
        return self._writer().open_review_request(**fields)

    def save(self, **fields: Any) -> dict:
        return self._writer().save(**fields)
