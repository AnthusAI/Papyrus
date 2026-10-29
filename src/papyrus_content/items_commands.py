"""`papyrus items ...`: commands over the stories (Items) of a site."""

from __future__ import annotations

import json

from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_options, resolve_mutation_apply
from .story_from_reference import plan_reference_links
from .story_reporting import STORY_REFERENCE_ROLES, link_reference_to_story


def items_link_references(flags: list[str]) -> None:
    """papyrus items link-references --site KEY [--role consulted|cited|based_on] [--json] [--dry-run]

    Finds the stories whose text links to the ``sourceUri`` of a Reference of the site (addresses match after the tracking
    parameters, fragment, ``www.`` and trailing slash are dropped) and writes the missing links. A story that matches one
    Reference is ``based_on`` it; one that matches several cites them, unless ``--role`` says otherwise. The backend is the one
    ``PAPYRUS_GRAPHQL_ENDPOINT`` names, as for every command; ``--site`` names it in the output. Safe to repeat: a link that exists is left as it is."""
    options = parse_options(flags)
    site = normalize_string(options.get("site"))
    if not site:
        raise ValueError("items link-references requires --site <key>.")
    role = normalize_string(options.get("role"))
    if role and role not in STORY_REFERENCE_ROLES:
        raise ValueError(f"--role must be one of {', '.join(STORY_REFERENCE_ROLES)}.")
    apply = resolve_mutation_apply(options, "items link-references")
    client, _ = create_authoring_client()
    plan = plan_reference_links(client, role=role)
    wanted = [row for row in plan if not row["exists"]]
    if options.get("json"):
        print(json.dumps({"site": site, "mode": "write" if apply else "dry run", "links": plan}, indent=2))
    else:
        for row in plan:
            state = "exists" if row["exists"] else ("write" if apply else "would link")
            print("\t".join(["items", "link-references", site, row["itemId"], row["referenceId"], row["role"], state, row["sourceUri"]]))
    written = 0
    if apply:
        for row in wanted:
            link_reference_to_story(client, row["lineageId"], row["referenceId"], role=row["role"], actor="papyrus-cli")
            written += 1
    print(f"items\tlink-references\t{site}\t{len(plan)} match(es)\t{len(plan) - len(wanted)} already linked\t{written if apply else len(wanted)} {'written' if apply else 'would be written (dry run)'}")
