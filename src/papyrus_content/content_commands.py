from __future__ import annotations

import os

from .env import graphql_endpoint
from .graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client
from .options import normalize_string, parse_comma_list, parse_options


def _caller_identity_arn() -> str:
    import boto3

    return str(boto3.client("sts").get_caller_identity().get("Arn") or "unknown")


def content_inspect(_flags: list[str]) -> None:
    endpoint = graphql_endpoint()
    client = PapyrusGraphQLAuthoringClient(endpoint=endpoint)
    client.inspect_reachability()

    print(f"GraphQL endpoint: {endpoint}")
    print("Auth source: AWS credential chain (IAM, SigV4)")
    print(f"AWS profile: {os.environ.get('AWS_PROFILE') or 'default chain'}")
    print(f"AWS caller: {_caller_identity_arn()}")
    print("GraphQL reachability: ok")


def content_schema_check(flags: list[str]) -> None:
    options = parse_options(flags)
    type_name = normalize_string(options.get("type")) or "Assignment"
    required_fields = parse_comma_list(options.get("fields") or options.get("field")) or []
    client, _ = create_authoring_client()
    fields = client.graphql_type_field_names(type_name)
    missing = [field for field in required_fields if field not in fields]
    print(f"schema-check\ttype\t{type_name}")
    print(f"schema-check\tfields\t{len(fields)}")
    if required_fields:
        print(f"schema-check\trequired\t{','.join(required_fields)}")
    if missing:
        print(f"schema-check\tmissing\t{','.join(missing)}")
        raise SystemExit(1)
    print("schema-check\tok\ttrue")


def content_list(subject: str | None, _flags: list[str]) -> None:
    if subject != "articles":
        raise ValueError("content list currently supports only: articles")
    client, _ = create_authoring_client()
    for article in client.list_published_articles():
        slug = article.get("slug") or article.get("id")
        headline = article.get("headline") or article.get("title") or article.get("id")
        print(f"{slug}\t{headline}")
