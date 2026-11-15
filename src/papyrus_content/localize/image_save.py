"""Save a language variant of a picture into a translation (``papyrus figures localize --save``, ``papyrus figures variant``). Optional, never required.

The variant is stored like any picture the translation owns (``stories save-version --images``: the same plan, the same ``MediaAsset`` rows and S3 objects, the
same renditions, a light and a dark file), the translation's figure and cover are pointed at it, and the front matter records which original it stands in
for (``image_variants``). The result is a new, unpublished-state-preserving version of the translation lineage (``<story>--<language>``), written the way a
person's save is (``save_story_version``), carrying the translation's provenance so the next translation run still finds its alignment. The original Story is
never written.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..item_language import localization_lineage_id
from .image_variants import ImageVariant, apply_variant, normalize

DARK_SUFFIX = ".dark"


def _stage_files(light: Path, dark: Path | None, folder: Path) -> tuple[str, str | None]:
    """Copy the pictures (and the figure sidecar, so the light-only check knows a figure) into ``folder`` under names that pair by name; returns their names."""
    suffix = light.suffix.lower()
    light_name = light.name
    shutil.copy2(light, folder / light_name)
    sidecar = light.with_name(light.stem + ".figure.json")
    if sidecar.is_file():
        shutil.copy2(sidecar, folder / sidecar.name)
    if dark is None:
        return light_name, None
    dark_name = f"{light.stem}{DARK_SUFFIX}{suffix}"
    shutil.copy2(dark, folder / dark_name)
    return light_name, dark_name


def save_variant(client, *, story: str, language: str, original: str, light: Path, dark: Path | None, reason: str, author: str,
                 texts: dict[str, str] | None = None, apply: bool = True, require_dark: bool | None = None, bucket: str | None = None,
                 pool_id: str | None = None) -> list[str]:
    """Output lines. ``original`` is the stored path of the picture the variant stands in for, as the Story's body or front matter names it.
    ``require_dark`` None reads the site's ``requireDarkFigures`` setting only when a figure has no dark picture (as ``save-version`` does)."""
    from ..story_images import dark_figures_required, existing_assets, light_only_figure_error, open_media_store, plan_lines, plan_story_images, upload_planned_images
    from ..story_reporting import current_story_version, planned_version_record_id, save_story_version, story_versions
    from ..story_commands import _site_requires_dark_figures
    from .record import carry_provenance

    lineage = localization_lineage_id(story, language)
    try:
        latest = current_story_version(client, lineage)
    except Exception as error:  # noqa: BLE001 - say what is missing instead of the lookup's own words
        raise ValueError(f"{story} has no {language} translation yet ({lineage}). Translate it first (papyrus.story.localize); a figure variant belongs to a translation.") from error
    import json

    metadata = json.loads(latest["metadata"]) if isinstance(latest.get("metadata"), str) else dict(latest.get("metadata") or {})
    original = normalize(original)
    from .image_variants import read_variants, remove_variant

    current_front_matter, current_body = metadata.get("frontMatterYaml"), latest.get("bodyMarkus") or ""
    for earlier in read_variants(current_front_matter):   # localizing a picture again replaces its variant: name the original or the variant, either works
        if original in (earlier.original, earlier.src):
            current_front_matter, current_body = remove_variant(current_front_matter, current_body, earlier)
            original = earlier.original
    with tempfile.TemporaryDirectory(prefix="papyrus-variant-") as scratch:
        folder = Path(scratch)
        light_name, dark_name = _stage_files(light, dark, folder)
        draft = ImageVariant(original, light_name, language, "", dark_name or "")
        front_matter, body, places = apply_variant(current_front_matter, current_body, draft, texts)   # to learn the stored paths
        if not places:
            raise ValueError(f"the {language} translation shows no picture stored as {original}, so there is nothing to localize. "
                             "Its figures and cover are named in its body and front matter (`papyrus stories pull`).")
        stored = [row for version in story_versions(client, lineage) for row in client.list_by_index("mediaAssetsByItemAndSortKey", version["id"])]
        plan = plan_story_images(body, folder, slug=latest["slug"], existing=existing_assets(stored), front_matter=front_matter)
        paths = {image.ref: image.src_path for image in plan.images}
        final = ImageVariant(original, paths[light_name], language, "", paths.get(dark_name or "", ""))
        if plan.light_only_figures:
            refuse, why = dark_figures_required(bool(require_dark), os.environ.get("PAPYRUS_REQUIRE_DARK_FIGURES"), lambda: _site_requires_dark_figures(client))
            if refuse:
                raise ValueError(light_only_figure_error(plan, why))
        saved_front_matter, saved_body, _ = apply_variant(current_front_matter, current_body, final, texts)
        number = int(latest.get("versionNumber") or 1) + 1
        header = f"figures\tvariant\t{lineage}\tversion {number}\t"
        lines = [header + ("write" if apply else "dry run"), f"figures\tvariant\toriginal\t{original}", f"figures\tvariant\tvariant\t{final.src}"
                 + (f"\t{final.src_dark}" if final.src_dark else "")]
        lines += plan_lines(plan, planned_version_record_id(client, lineage))
        if not apply:
            return lines
        if plan.images:
            store = open_media_store(bucket, pool_id)
            lines += [f"figures\tvariant\timage-{outcome}\t{image.storage_path}" for image, outcome in upload_planned_images(plan, store)]
        record = save_story_version(client, lineage, front_matter_yaml=saved_front_matter, body_markus=saved_body, actor=author, change_reason=reason,
                                    media_rows=plan.media_rows)
    carry_provenance(client, latest, record)
    lines.append(f"figures\tvariant\tsaved\t{record['id']}")
    return lines
