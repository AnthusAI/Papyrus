"""Basic content measurements of a Story: what ``papyrus stories measure`` prints and ``stories save-version`` prints and stores.

Every number comes from Humanus (``humanus.measure`` and ``humanus.diff``): size, structure, sourcing and the size of a change. Papyrus
holds no counting logic of its own. It only hands Humanus the text, the language and the headline, dek and blurb the front matter names,
and lays the answer out as rows. The numbers are guidance for an editor or an agent; nothing here compares them with a limit.
"""
from __future__ import annotations

from typing import Any

import humanus

from .item_front_matter import dek_from_front_matter
from .publishing import _load_front_matter, columns_from_front_matter


def story_measurements(body: str, front_matter_yaml: str | None, language: str, previous_body: str | None = None, previous_version: int | None = None) -> dict[str, Any]:
    """The measurements of one version's text, and, given the version it replaces, how much it changed from that one.

    The headline, dek and blurb come from the front matter (the headline is its title); one the front matter does not have is measured as absent.
    """
    front_matter = _load_front_matter(front_matter_yaml)
    blurb = front_matter.get("blurb")
    texts = {
        "headline": columns_from_front_matter(front_matter).get("headline") or "",
        "dek": dek_from_front_matter(front_matter) or "",
        "blurb": blurb.strip() if isinstance(blurb, str) else "",
    }
    result: dict[str, Any] = {"humanusVersion": humanus.__version__, "measure": humanus.measure(body, language, **texts)}
    if previous_body is not None:
        result["changeFromPrevious"] = {"version": previous_version, **humanus.diff(previous_body, body, language)}
    return result


def measurement_rows(group: str, command: str, label: str, measurements: dict[str, Any]) -> list[str]:
    """Tab-separated rows (``stories measure``'s and ``save-version``'s output style), one per measurement group."""
    measure = measurements["measure"]
    head = f"{group}\t{command}\t{label}\t"
    size, structure, sourcing = measure["size"], measure["structure"], measure["sourcing"]
    rows = [
        head + f"size\tunit={size['unit']}\tunits={size['units']}\treadingMinutes={size['readingMinutes']}",
        head + "structure\t" + "\t".join([
            f"sections={structure['sections']}", f"paragraphs={structure['paragraphs']}", f"longestParagraph={structure['longestParagraph']}",
            f"longestSentence={structure['longestSentence']}",
            *(f"{name}={'present(' + str(structure[name]['length']) + ')' if structure[name]['present'] else 'absent'}" for name in ("headline", "dek", "blurb") if name in structure),
        ]),
        head + "sourcing\t" + "\t".join([
            f"links={sourcing['links']}", f"citations={sourcing['citations']}", f"per500={_number(sourcing['per500'])}",
            f"paragraphsWithoutSource={sourcing['paragraphsWithoutSource']}", f"shareParagraphsWithoutSource={_number(sourcing['shareParagraphsWithoutSource'])}",
        ]),
    ]
    change = measurements.get("changeFromPrevious")
    if change:
        against = f"vs version {change['version']}" if change.get("version") else "vs the previous version"
        rows.append(head + f"change\t{against}\tadded={change['added']}\tremoved={change['removed']}\trewritten={change['rewritten']}\t"
                    f"unchanged={change['unchanged']}\tshareChanged={change['shareChanged']}")
    rows.append(head + f"note\tguidance from Humanus {measurements['humanusVersion']}, not limits: nothing is blocked or required by these numbers")
    return rows


def _number(value: Any) -> str:
    return "n/a" if value is None else str(value)
