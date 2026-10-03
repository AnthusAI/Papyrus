"""Markus static-site build pipeline for Papyrus (PPY-88f77b).

``build_markus_site`` has been the module's public entry point since PPY-88f77b
and keeps its original behaviour: the responsive-image and inline-citation
capabilities added later are opt-in parameters that default to ``None``.
"""

from .build import build_markus_site, render_fragment
from .citations import CitationRendering, format_apa
from .content_markup import prepare_page, resolve_fragment
from .images import ImagePipeline, ImageRequest, with_layouts

__all__ = [
    "build_markus_site",
    "render_fragment",
    "CitationRendering",
    "format_apa",
    "ImagePipeline",
    "ImageRequest",
    "with_layouts",
    "prepare_page",
    "resolve_fragment",
]
