"""Where a runner finds a site's agent policy (PPY-c8175e): the site's tenant id and its bucket.

A top-level module with no dependencies, because the monitoring router's package holds top-level modules only and the router copies this
onto every runner request it sends.
"""
from __future__ import annotations

import re

S3_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{2,62}$")


def policy_location(publication: dict) -> dict[str, str]:
    """The ``tenantId`` and ``siteBucket`` of a router publication that name where its site policy is; what it does not name is left out."""
    return {key: publication[key] for key in ("tenantId", "siteBucket") if publication.get(key)}
