#!/usr/bin/env python3
"""Read-only export of one site's review requests and the AI drafts they cover, for the local Notification Center preview.

Reads ReviewRequests and the Proposals their links name through the AppSync API with IAM (SigV4). Nothing is written to AWS. The
fixture holds no people: who answered, who decided and the history of every Proposal are dropped, and the export refuses to write
if anything that looks like an email address or an AWS ARN is left in it. The pending References, their pictures and the
Cyclotron's predictions come from the References fixture (scripts/export-reference-feed-fixture.py); the cards of a draft find
their pictures through the References its sources point to.

    AWS_PROFILE=papyrus-production python3 scripts/export-notification-center-fixture.py \\
        --graphql-url https://<api-id>.appsync-api.us-east-1.amazonaws.com/graphql \\
        [--region us-east-1] [--output .local-preview/notification-center-fixture.json]

Then run the preview with PAPYRUS_FEED_FIXTURE=.local-preview/reference-feed-fixture.json and
PAPYRUS_NOTIFICATION_FIXTURE=.local-preview/notification-center-fixture.json (see docs/notification-center.md).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUEST_FIELDS = "id subject mode reason ask raisedBy raisedAt deadline state answer links history appliedIn updatedAt"
PROPOSAL_FIELDS = "id kind title summary body state held evidence createdAt"
JSON_FIELDS = ("subject", "answer", "links", "history", "appliedIn")
PERSON = "an editor"
SENSITIVE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|arn:aws[\w:/.-]*")


def helpers():
    spec = importlib.util.spec_from_file_location("reference_feed_export", ROOT / "scripts" / "export-reference-feed-fixture.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def anonymous_request(row: dict) -> dict:
    """The request as the console reads it (JSON fields as strings), with every person removed."""
    parsed = {key: load(row.get(key)) for key in JSON_FIELDS}
    answer = parsed["answer"]
    if isinstance(answer, dict):
        answer["by"] = PERSON
        for entry in answer.get("drafts") or []:
            entry["by"] = PERSON
    links = parsed["links"] or []
    for link in links:
        if isinstance(link.get("decision"), dict):
            link["decision"]["by"] = PERSON
    history = [{key: value for key, value in entry.items() if key != "by"} for entry in (parsed["history"] or [])]
    applied = parsed["appliedIn"]
    if isinstance(applied, dict):
        applied.pop("by", None)
    out = {key: value for key, value in row.items() if key not in JSON_FIELDS}
    out.update(subject=json.dumps(parsed["subject"]), answer=json.dumps(answer) if answer else None, links=json.dumps(links),
               history=json.dumps(history), appliedIn=json.dumps(applied) if applied else None)
    return out


def anonymous_proposal(row: dict) -> dict:
    return {key: value for key, value in row.items() if key in PROPOSAL_FIELDS.split()}


def proposal_ids(request: dict) -> list[str]:
    links = load(request.get("links")) or []
    ids = [link["id"] for link in links if link.get("type") == "proposal" and link.get("id")]
    subject = load(request.get("subject")) or {}
    if not ids and subject.get("type") == "proposal":
        ids = [subject["id"]]
    return list(dict.fromkeys(ids))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graphql-url", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--output", default=str(ROOT / ".local-preview" / "notification-center-fixture.json"))
    args = parser.parse_args()
    if not args.graphql_url.startswith("https://") or "appsync-api" not in args.graphql_url:
        raise SystemExit("--graphql-url must be an AppSync https GraphQL address.")

    import boto3

    export = helpers()
    session = boto3.Session()
    account = session.client("sts").get_caller_identity()["Account"]
    print(f"read-only export as account {account}", file=sys.stderr)

    rows = export.list_all(session, args.graphql_url, args.region, "listReviewRequests", REQUEST_FIELDS)
    wanted = [proposal_id for row in rows for proposal_id in proposal_ids(row)]
    drafts = []
    for proposal_id in dict.fromkeys(wanted):
        found = export.signed_graphql(session, args.graphql_url, args.region,
                                      f"query($id:ID!){{ getProposal(id:$id){{ {PROPOSAL_FIELDS} }} }}", {"id": proposal_id})["getProposal"]
        if found:
            drafts.append(anonymous_proposal(found))
    fixture = {
        "schema": "papyrus-notification-center-fixture/1",
        "exportedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "requests": [anonymous_request(row) for row in rows],
        "drafts": drafts,
    }
    text = json.dumps(fixture, indent=1) + "\n"
    leak = SENSITIVE.search(text)
    if leak:
        raise SystemExit(f"Refusing to write: the export still contains {leak.group(0)!r}.")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"{output}: {len(rows)} review requests, {len(drafts)} drafts", file=sys.stderr)


if __name__ == "__main__":
    main()
