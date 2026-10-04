#!/usr/bin/env python3
"""Delete all GraphQL content from the configured sandbox (authoring JWT required)."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from papyrus_content.env import load_dotenv
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient

DELETE_ORDER = [
    "PublishedMediaAsset",
    "PublishedEditionItem",
    "PublishedItem",
    "PublishedEdition",
    "PublishedCategory",
    "PublishedCategorySet",
    "MediaAsset",
    "ItemTag",
    "EditionItem",
    "Item",
    "Tag",
    "Edition",
    "ModelAttachment",
    "KnowledgeRawPayload",
    "SteeringDecision",
    "SteeringProposal",
    "SemanticRelation",
    "SemanticRelationType",
    "AssignmentEvent",
    "Assignment",
    "NewsroomSection",
    "SemanticNode",
    "Message",
    "ReferenceAttachment",
    "Reference",
    "CategoryKeyword",
    "LexicalSteeringRule",
    "Category",
    "CategorySet",
    "KnowledgeArtifact",
    "KnowledgeImportRun",
    "KnowledgeCorpus",
]


def delete_concurrency() -> int:
    raw = os.environ.get("PAPYRUS_DELETE_CONCURRENCY", "16")
    parsed = int(raw)
    return max(1, min(parsed, 24))


def delete_records(model_name: str, records: list[dict]) -> int:
    record_ids = [record["id"] for record in records if record.get("id")]
    if not record_ids:
        return 0
    concurrency = delete_concurrency()

    def delete_one(record_id: str) -> None:
        PapyrusGraphQLAuthoringClient().delete_record(model_name, record_id)

    deleted = 0
    with ThreadPoolExecutor(max_workers=min(concurrency, len(record_ids))) as pool:
        futures = [pool.submit(delete_one, record_id) for record_id in record_ids]
        for future in as_completed(futures):
            future.result()
            deleted += 1
    return deleted


def main() -> int:
    load_dotenv()
    client = PapyrusGraphQLAuthoringClient()
    for model_name in DELETE_ORDER:
        total_deleted = 0
        for pass_num in range(1, 21):
            try:
                records = client.safe_list_records(model_name)
            except KeyError:
                print(f"delete\tskip\t{model_name}\tunsupported model")
                break
            except Exception as error:  # noqa: BLE001
                message = str(error)
                if "FieldUndefined" in message or "not available" in message.lower():
                    print(f"delete\tskip\t{model_name}\t{message}")
                    break
                raise
            print(f"delete\t{model_name}\tpass={pass_num}\t{len(records)}")
            if not records:
                break
            total_deleted += delete_records(model_name, records)
        else:
            print(f"delete\tfailed\t{model_name}\tdid not drain after 20 passes", file=sys.stderr)
            return 1
        print(f"delete\tdone\t{model_name}\tdeleted={total_deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
