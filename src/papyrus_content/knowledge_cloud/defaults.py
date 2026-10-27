"""What a publication's knowledge run needs from its operator, with a generic default for each, so a new site needs none of it.

A site that wants its own entity vocabulary, stop words or review guidance puts them in ``config/`` of the run state (or, for the beats
and concept kinds, in its ``knowledgeRun`` settings); a site that does not gets these. The defaults are written into the state on the first
stage that needs them, so the operator can then edit the seeded file.
"""

from __future__ import annotations

import json

VOCABULARY_FILE = "vocabulary.yml"
OUTPUTS_FILE = "amplify_outputs.json"

#: The closed vocabulary of a publication that has not written one: the four kinds almost any subject has. ``label`` is the only
#: instruction the extraction model gets for a kind, so each is short and plain.
DEFAULT_VOCABULARY = """\
version: 1
publication: {publication}
entity_kinds:
  - {{key: organization, label: company, lab, institution or other organization}}
  - {{key: product, label: product, service, model or software}}
  - {{key: person, label: named person}}
  - {{key: topic, label: subject, technique or concept}}
relation_types:
  - {{key: made_by, label: made by}}
  - {{key: built_on, label: built on}}
  - {{key: member_of, label: member of}}
"""


def default_vocabulary(publication: str) -> str:
    return DEFAULT_VOCABULARY.format(publication=publication)


def default_outputs(api_id: str, region: str) -> str:
    """The only part of ``amplify_outputs.json`` the run reads: the GraphQL endpoint of the publication's AppSync API."""
    return json.dumps({"data": {"url": f"https://{api_id}.appsync-api.{region}.amazonaws.com/graphql"}}, indent=2) + "\n"
