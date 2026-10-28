"""The per-publication web-search monitors: which publications, and the config items that seed them.

One monitor per publication, `web-<publicationId>`. The six publications decided by the shared relevance Cyclotron each have a
router config that lists all six and reuses the `hn` router's `cyclotron` block and publication entries as stored, so a find
by any of the six monitors is decided for every publication in one combined request, as Hacker News items are (a successor
run is followed by re-seeding rather than by editing code). Distinctive Mark has no Cyclotron yet: its router config is
`decisions: "hold"` (collect and enrich; never decide) with no `cyclotron` block, until Cyclotron bootstraps its own run.

Every router config carries `holdDecisions: true`, so enrichment runs and no decide request is posted until an operator
flips it (`seed_router_config.py --set holdDecisions=false`). Every monitor starts disabled; its queries are `QUERY#` records
(`papyrus monitors web-queries` drafts them for review).
"""
from __future__ import annotations

import json
from pathlib import Path

from .monitoring_web import DEFAULT_INTERVAL_SECONDS, TAVILY_SOURCE_URL, WEB_SEARCH

#: Which publications have a web monitor, and which of them have no Cyclotron yet: configuration, not code.
_PUBLICATIONS = json.loads((Path(__file__).resolve().parents[2] / "config" / "web-monitors.json").read_text())
SHARED_CYCLOTRON = tuple(_PUBLICATIONS["sharedCyclotron"])
DISTINCTIVE = "distinctive"
WEB_PUBLICATIONS = (*SHARED_CYCLOTRON, DISTINCTIVE)
DISTINCTIVE_ENTRY = {   # as in the TTAB router config, without that monitor's procedure trigger and key
    "publicationId": DISTINCTIVE, "site": "distinctive-mark.com",
    "appsyncEndpoint": "https://lzc75j6qdjboblirpdtsalilnq.appsync-api.us-east-1.amazonaws.com/graphql"}


def monitor_id(publication_id: str) -> str:
    if publication_id not in WEB_PUBLICATIONS:
        raise ValueError(f"Unknown publication {publication_id}; expected one of {', '.join(WEB_PUBLICATIONS)}")
    return f"web-{publication_id}"


def monitor_config(publication_id: str, *, enabled: bool = False, topic: str = "news",
                   interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> dict:
    """The monitor's CONFIG. Its queries are `QUERY#` records (see `monitoring_web.query_record`). The six shared-Cyclotron
    monitors share one `candidateGroup`, so a story two of them find is one candidate, decided once for all six publications."""
    return {"pk": f"MONITOR#{monitor_id(publication_id)}", "sk": "CONFIG", "sourceType": WEB_SEARCH,
            "sourceUrl": TAVILY_SOURCE_URL, "intervalSeconds": interval_seconds, "enabled": enabled,
            "publicationId": publication_id, "topic": topic,
            **({"candidateGroup": "shared"} if publication_id in SHARED_CYCLOTRON else {})}


def router_config(publication_id: str, hn_router: dict) -> dict:
    """The monitor's `CONFIG#router`, built from the stored `hn` router config. The shared-Cyclotron monitors list all six
    shared publications and the hn cyclotron block, so a find is decided for every one of them in one combined request, as
    Hacker News items are. Distinctive Mark routes on its own and only holds."""
    key = {"pk": f"MONITOR#{monitor_id(publication_id)}", "sk": "CONFIG#router"}
    if publication_id == DISTINCTIVE:
        return {**key, "mode": "live", "enabled": True, "decisions": "hold", "holdDecisions": True,
                "publications": [dict(DISTINCTIVE_ENTRY)]}
    by_id = {p.get("publicationId"): p for p in hn_router.get("publications") or []}
    missing = [p for p in SHARED_CYCLOTRON if p not in by_id]
    if missing or not isinstance(hn_router.get("cyclotron"), dict):
        raise ValueError(f"The hn router config has no {', '.join(missing) or 'cyclotron block'} to reuse")
    return {**key, "mode": "live", "enabled": True, "decisions": "cyclotron", "holdDecisions": True,
            "publications": [dict(by_id[p]) for p in SHARED_CYCLOTRON], "cyclotron": dict(hn_router["cyclotron"])}
