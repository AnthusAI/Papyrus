"""The per-publication web-search monitors: which publications, and the config items that seed them.

One monitor per publication, `web-<publicationId>`, each with its own `CONFIG#router` listing only that publication.
Six publications are decided by the shared relevance Cyclotron: their router configs reuse the `hn` router's `cyclotron`
block and publication entries as stored, so a successor run is followed by re-seeding rather than by editing code.
Distinctive Mark has no Cyclotron yet: its router config is `decisions: "hold"` (collect and enrich; never decide) and has
no `cyclotron` block, until Cyclotron bootstraps its own run and sends the settings.

Every router config carries `holdDecisions: true`, so enrichment runs and no decide request is posted until an operator
flips it (`seed_router_config.py --set holdDecisions=false`). Every monitor starts disabled with no queries: the proposed
queries (`papyrus monitors web-queries`) are reviewed first.
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


def monitor_config(publication_id: str, queries=(), *, enabled: bool = False, topic: str = "news",
                   interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> dict:
    return {"pk": f"MONITOR#{monitor_id(publication_id)}", "sk": "CONFIG", "sourceType": WEB_SEARCH,
            "sourceUrl": TAVILY_SOURCE_URL, "intervalSeconds": interval_seconds, "enabled": enabled,
            "topic": topic, "queries": list(queries)}


def router_config(publication_id: str, hn_router: dict) -> dict:
    """The monitor's `CONFIG#router`, built from the stored `hn` router config."""
    key = {"pk": f"MONITOR#{monitor_id(publication_id)}", "sk": "CONFIG#router"}
    if publication_id == DISTINCTIVE:
        return {**key, "mode": "live", "enabled": True, "decisions": "hold", "holdDecisions": True, "feedback": False,
                "publications": [dict(DISTINCTIVE_ENTRY)]}
    entries = [p for p in hn_router.get("publications") or [] if p.get("publicationId") == publication_id]
    if len(entries) != 1 or not isinstance(hn_router.get("cyclotron"), dict):
        raise ValueError(f"The hn router config has no single {publication_id} entry and cyclotron block to reuse")
    return {**key, "mode": "live", "enabled": True, "decisions": "cyclotron", "holdDecisions": True, "feedback": False,
            "publications": [dict(entries[0])], "cyclotron": dict(hn_router["cyclotron"])}
