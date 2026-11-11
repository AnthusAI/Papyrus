"""Fill the notice-country list of infra/edge/consent-region-function.js from the one Python source.

    python infra/edge/generate_consent_region_function.py            # print the generated file
    python infra/edge/generate_consent_region_function.py --write    # rewrite it in place
    python infra/edge/generate_consent_region_function.py --settings web/projection.json   # a site's own overrides

Run it with ``PYTHONPATH=src``. Reads files and writes only the function file; it touches no AWS resource.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from papyrus_content.markus_renderer.consent import ConsentModeSettings, consent_mode_from_mapping

FUNCTION_PATH = Path(__file__).with_name("consent-region-function.js")
_BLOCK = re.compile(
    r"(// BEGIN GENERATED NOTICE COUNTRIES\n).*?(// END GENERATED NOTICE COUNTRIES)", re.S
)


def render_function(settings: ConsentModeSettings, template: str | None = None) -> str:
    template = FUNCTION_PATH.read_text() if template is None else template
    countries = [region for region in settings.denied_by_default_regions if re.fullmatch(r"[A-Z]{2}", region)]
    block = "var NOTICE_COUNTRIES = " + json.dumps(countries, separators=(",", ":")) + ";\n"
    return _BLOCK.sub(lambda m: m.group(1) + block + m.group(2), template, count=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--settings", type=Path, help="a projection.json whose chrome.consent_mode sets the regions")
    parser.add_argument("--write", action="store_true", help="rewrite the function file instead of printing")
    args = parser.parse_args()
    raw = {}
    if args.settings:
        raw = (json.loads(args.settings.read_text()).get("chrome") or {}).get("consent_mode") or {}
    text = render_function(consent_mode_from_mapping(raw))
    if args.write:
        FUNCTION_PATH.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
