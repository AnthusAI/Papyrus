#!/usr/bin/env python3
"""Read-only replay of the idea minimum standard on one site's accepted References (PPY-f40b36; src/papyrus_content/ideas/standard_replay.py).

For the accepted References that have no story yet it runs the single-item path twice on the same References in the same order, once with
``minimumStandard: summary`` and once with ``more-than-summary``, and writes a result, a blind sample of about twenty same-Reference pairs for the owner to mark,
and the key. Both runs are dry runs: the model is asked (GPT-6 Luna) and the draft checked, and NOTHING is written to any backend; the backend client refuses
anything that is not a read, and no curation flag is raised. The only files written are the three below, on this machine.

It spends real money on the model, so it will not start without ``--max-cost-usd``; the ceiling is checked before every call against the cost the API reports
for the calls already made, and the two runs share it.

Run it from the site's repository root (where ``amplify_outputs.json`` is), signed in the way ``papyrus ideas monitor-stories`` needs:

    OPENAI_API_KEY=... \\
    python3 <engine checkout>/scripts/replay_idea_standard.py --site <site key> [--corpus-key <corpus key>] --max-cost-usd 1.00 [--pairs 20] [--references N]

The model key is read from the OPENAI_API_KEY environment variable, else from ``openai.apiKey`` in the Papyrus config (``PAPYRUS_CONFIG`` or
``.papyrus/config.yaml``), through ``papyrus_config.resolve_openai_api_key``. It is held in memory and is never printed or written. The backend is reached
the way the CLI does: ``papyrus login`` (an editor session), or ``PAPYRUS_GRAPHQL_AUTH=iam`` with ``AWS_PROFILE=papyrus-production``; the endpoint comes from
``amplify_outputs.json`` or ``PAPYRUS_GRAPHQL_ENDPOINT``.

Output (``--output-dir``, default ``./idea-standard-replay/<site>-<UTC time>``): ``result.json``, ``sample.md``, ``key.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from papyrus_content.env import load_dotenv  # noqa: E402
from papyrus_content.graphql_authoring import create_authoring_client  # noqa: E402
from papyrus_content.ideas import monitor_stories, synthesis  # noqa: E402
from papyrus_content.ideas.standard_replay import DEFAULT_PAIRS, replay_site, write_outputs  # noqa: E402
from papyrus_content.papyrus_config import resolve_openai_api_key  # noqa: E402


def parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", required=True, help="the publication key")
    parser.add_argument("--corpus-key", help="the knowledge corpus key when it is not the site key")
    parser.add_argument("--max-cost-usd", type=float, required=True, help="ceiling on the real model cost of both runs together")
    parser.add_argument("--pairs", type=int, default=DEFAULT_PAIRS, help="pairs in the sample (default %(default)s)")
    parser.add_argument("--references", type=int, help="only this many References, chosen at random (default: all candidates, as far as the ceiling allows)")
    parser.add_argument("--seed", type=int, default=20261102, help="seed for the choice and the order of the pairs")
    parser.add_argument("--model", default=synthesis.DEFAULT_MODEL)
    parser.add_argument("--explore", action="store_true", help="follow links through trackers and search for a page that cannot be read, as the router does (default: read the address only)")
    parser.add_argument("--output-dir", help="where to write result.json, sample.md and key.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = parse(argv)
    if options.max_cost_usd <= 0:
        print("--max-cost-usd must be above zero.", file=sys.stderr)
        return 2
    load_dotenv()
    key = resolve_openai_api_key()
    if not key:
        print("The replay asks the model and needs OPENAI_API_KEY (or openai.apiKey in the Papyrus config).", file=sys.stderr)
        return 2
    client, _ = create_authoring_client()
    now = datetime.now(timezone.utc)
    result = replay_site(
        client, site=options.site, corpus_key=options.corpus_key, transport=synthesis.openai_transport(key), max_cost_usd=options.max_cost_usd, pairs=options.pairs,
        references=options.references, seed=options.seed, model=options.model, explorer=monitor_stories.explore_item if options.explore else None, now=now,
    )
    directory = Path(options.output_dir) if options.output_dir else Path("idea-standard-replay") / f"{options.site}-{now.strftime('%Y%m%dT%H%M%SZ')}"
    paths = write_outputs(result, directory)
    print(json.dumps({"site": result["site"], "referencesOffered": result["referencesOffered"], "costUsd": result["costUsd"], "pairs": result["pairs"], "arms": result["arms"]}, indent=2, sort_keys=True))
    print(f"wrote {paths['result']}, {paths['sample']} and {paths['key']} (keep the key away from whoever marks the sample)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
