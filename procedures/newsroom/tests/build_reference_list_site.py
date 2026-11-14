"""Write a synthetic public site with long, paged Reference lists to a directory, for ``scripts/browser-reference-list-scroll.ts`` and the screenshots.

    python -m procedures.newsroom.tests.build_reference_list_site <directory> [accepted] [recommended]

The site is the standard front end's own output for the ``home-page`` fixture with a ``wire`` page of two paged lists and a few pictures.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from papyrus_content.env import PAPYRUS_ROOT
from procedures.newsroom.tests.reference_list_support import project, snapshot

THEME = PAPYRUS_ROOT / "features" / "fixtures" / "newsletter-site" / "css" / "site-theme.css"
COLOURS = ("#C6F432", "#BFD7EA", "#F2C6B4", "#D9D2E9")


def picture(number: int) -> str:
    colour = COLOURS[number % len(COLOURS)]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180"><rect width="320" height="180" fill="{colour}"/>'
        f'<circle cx="{60 + number % 5 * 50}" cy="90" r="{30 + number % 3 * 12}" fill="#161412" fill-opacity=".18"/></svg>'
    )


def build(destination: Path, accepted: int = 130, recommended: int = 40) -> Path:
    document = snapshot(accepted, recommended)
    for position, found in enumerate(document["references"]):
        if position % 3 != 2:
            found["image"] = f"/assets/thumb-{position % 4}.svg"
    site = project(document, first=6, page_size=12, extra_files={"css/site-theme.css": THEME.read_bytes()})
    try:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(site.out, destination)
        for number in range(4):
            (destination / "assets").mkdir(exist_ok=True)
            (destination / "assets" / f"thumb-{number}.svg").write_text(picture(number), encoding="utf-8")
    finally:
        site.cleanup()
    return destination


if __name__ == "__main__":
    target = build(Path(sys.argv[1]), *(int(value) for value in sys.argv[2:4]))
    print(target)
