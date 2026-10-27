#!/usr/bin/env python3
"""Read-only export of one corpus' References into a fixture for the local References feed preview.

Reads References, their source attachments, their current relevance decisions and their curation status through the AppSync
API with IAM (SigV4), and fetches each source page's link-preview image and description (the same read `papyrus references
enrich-images` stores). Nothing is written to AWS. The fixture holds no secrets and no people: curation actors, notes and
decision provenance identifiers are dropped. It is written under `.local-preview/` (gitignored).

    AWS_PROFILE=papyrus-production python3 scripts/export-reference-feed-fixture.py \\
        --corpus knowledge-corpus-anth-us --graphql-url https://<api-id>.appsync-api.us-east-1.amazonaws.com/graphql \\
        [--region us-east-1] [--output .local-preview/reference-feed-fixture.json]

Get the URL in its own command: `aws appsync get-graphql-api --api-id <id> --query graphqlApi.uris.GRAPHQL --output text`.
Then run the preview with `PAPYRUS_FEED_FIXTURE=.local-preview/reference-feed-fixture.json npm run dev:preview`.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

REFERENCE_FIELDS = (
    "id lineageId versionNumber versionState corpusId externalItemId title sourceUri mediaType sourcePublishedAt sourceUpdatedAt "
    "retrievedAt importedAt createdAt curationStatus curationStatusUpdatedAt"
)
ATTACHMENT_FIELDS = "id referenceId referenceLineageId referenceVersionNumber referenceVersionKey role sortKey sourceUri filename mediaType importedAt"
RELATION_FIELDS = (
    "id relationState predicate subjectKind subjectId subjectLineageId objectKind objectId objectLineageId subjectStateKey objectStateKey "
    "objectSubjectStateKey predicateObjectStateKey subjectVersionKey objectVersionKey confidence modelVersion reviewRecommended "
    "classifierId createdAt importedAt metadata"
)
KEPT_DECISION_KEYS = ("decisionId", "label", "labels", "positiveLabel", "reviewControl", "question", "cyclotronId", "decidedAt",
                      "reviewReason", "reviewDetail", "probabilities", "version")


def signed_graphql(session, url: str, region: str, query: str, variables: dict) -> dict:
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    body = json.dumps({"query": query, "variables": variables})
    request = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
    SigV4Auth(session.get_credentials(), "appsync", region).add_auth(request)
    http = urllib.request.Request(url, data=body.encode(), headers=dict(request.headers.items()), method="POST")
    with urllib.request.urlopen(http, timeout=60) as response:  # noqa: S310 - the AppSync https endpoint the operator passed
        payload = json.load(response)
    if payload.get("errors"):
        raise SystemExit(f"GraphQL error: {payload['errors'][0].get('message')}")
    return payload["data"]


def list_all(session, url: str, region: str, field: str, fields: str, filter_input: str = "") -> list[dict]:
    query = f"query($t:String){{ {field}(limit:1000,nextToken:$t{filter_input}){{ items{{ {fields} }} nextToken }} }}"
    rows: list[dict] = []
    token = None
    while True:
        page = signed_graphql(session, url, region, query, {"t": token})[field]
        rows += [row for row in page["items"] if row]
        token = page["nextToken"]
        if not token:
            return rows


def decision_relation(row: dict) -> dict:
    metadata = json.loads(row["metadata"]) if isinstance(row.get("metadata"), str) else (row.get("metadata") or {})
    kept = {key: metadata[key] for key in KEPT_DECISION_KEYS if key in metadata}
    provenance = metadata.get("provenance") or {}
    kept["provenance"] = {"labelSet": provenance.get("labelSet") or metadata.get("labels") or [], "system": provenance.get("system")}
    return {**{key: value for key, value in row.items() if key != "metadata"}, "metadata": json.dumps(kept)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--graphql-url", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--output", default=str(ROOT / ".local-preview" / "reference-feed-fixture.json"))
    parser.add_argument("--no-images", action="store_true", help="skip fetching source pages for preview images")
    args = parser.parse_args()
    if not args.graphql_url.startswith("https://") or "appsync-api" not in args.graphql_url:
        raise SystemExit("--graphql-url must be an AppSync https GraphQL address.")

    import boto3

    session = boto3.Session()
    account = session.client("sts").get_caller_identity()["Account"]
    print(f"read-only export as account {account}", file=sys.stderr)

    corpus_filter = f',filter:{{corpusId:{{eq:"{args.corpus}"}}}}'
    references = [row for row in list_all(session, args.graphql_url, args.region, "listReferences", REFERENCE_FIELDS, corpus_filter)
                  if row.get("versionState") in (None, "current")]
    lineages = {row["lineageId"] for row in references}
    attachments = [row for row in list_all(session, args.graphql_url, args.region, "listReferenceAttachments", ATTACHMENT_FIELDS)
                   if row["referenceLineageId"] in lineages]
    relations = [decision_relation(row) for row in list_all(
        session, args.graphql_url, args.region, "listSemanticRelations", RELATION_FIELDS,
        ',filter:{predicate:{eq:"relevance_decision_is"},relationState:{eq:"current"},subjectKind:{eq:"reference"}}')
        if row["subjectLineageId"] in lineages]

    if not args.no_images:
        from papyrus_content.link_exploration import explore
        from papyrus_content.reference_images import preview_attachment

        def preview(reference: dict) -> dict | None:
            found = explore(reference["sourceUri"], want_text=False, use_search=False)
            return preview_attachment(reference, found, datetime.now(timezone.utc)) if found.metadata and found.metadata.as_dict() else None

        with ThreadPoolExecutor(max_workers=8) as pool:
            for row in pool.map(preview, [reference for reference in references if reference.get("sourceUri")]):
                if row:
                    attachments.append(row)

    fixture = {
        "schema": "papyrus-reference-feed-fixture/1",
        "exportedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "corpusId": args.corpus,
        "references": references,
        "referenceAttachments": attachments,
        "semanticRelations": relations,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(fixture, indent=1) + "\n", encoding="utf-8")
    previews = sum(1 for row in attachments if row["role"] == "preview" and row.get("sourceUri"))
    print(f"{output}: {len(references)} references, {len(relations)} decisions, {previews} preview images", file=sys.stderr)


if __name__ == "__main__":
    main()
