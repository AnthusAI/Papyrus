#!/usr/bin/env python3
"""Read-only export of one site's review requests, for the local Notification Center preview.

Reads ReviewRequests through the AppSync API with IAM (SigV4), one state at a time from the review request state index (never by
listing the table; pass --tenant on a shared stack, whose state keys have the tenant in front). Nothing is written to AWS. The
fixture holds no people: who answered, who decided and the history of every request are dropped, and the export refuses to write
if anything that looks like an email address or an AWS ARN is left in it. The pending References, their pictures and the
Cyclotron's predictions come from the References fixture (scripts/export-reference-feed-fixture.py). A batch of ideas links to the
Idea column; the ideas themselves are stories, not part of this fixture.

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
STATES = ("open", "answered", "timed_out", "withdrawn")
STATE_FIELD = "listReviewRequestsByReviewStateKeyAndUpdatedAt"
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


def requests_in_state(export, session, url: str, region: str, state_key: str) -> list[dict]:
    query = (f"query($k:String!,$t:String){{ {STATE_FIELD}(reviewStateKey:$k,limit:1000,nextToken:$t){{ items{{ {REQUEST_FIELDS} }} nextToken }} }}")
    rows: list[dict] = []
    token = None
    while True:
        page = export.signed_graphql(session, url, region, query, {"k": state_key, "t": token})[STATE_FIELD]
        rows += [row for row in page["items"] if row]
        token = page["nextToken"]
        if not token:
            return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graphql-url", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--tenant", default="", help="the tenant in front of the state keys on a shared stack")
    parser.add_argument("--output", default=str(ROOT / ".local-preview" / "notification-center-fixture.json"))
    args = parser.parse_args()
    if not args.graphql_url.startswith("https://") or "appsync-api" not in args.graphql_url:
        raise SystemExit("--graphql-url must be an AppSync https GraphQL address.")

    import boto3

    export = helpers()
    session = boto3.Session()
    account = session.client("sts").get_caller_identity()["Account"]
    print(f"read-only export as account {account}", file=sys.stderr)

    prefix = f"{args.tenant}#" if args.tenant else ""
    rows = [row for state in STATES for row in requests_in_state(export, session, args.graphql_url, args.region, f"{prefix}review#{state}")]
    fixture = {
        "schema": "papyrus-notification-center-fixture/1",
        "exportedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "requests": [anonymous_request(row) for row in rows],
    }
    text = json.dumps(fixture, indent=1) + "\n"
    leak = SENSITIVE.search(text)
    if leak:
        raise SystemExit(f"Refusing to write: the export still contains {leak.group(0)!r}.")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"{output}: {len(rows)} review requests", file=sys.stderr)


if __name__ == "__main__":
    main()
