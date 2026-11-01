"""Unit tests for ``papyrus ops site copy`` against moto. No network."""

from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from .site_copy import CopyConfig, SiteCopier, SiteCopyError, parse_key_map, tables_by_model
from .site_copy_commands import site_copy

OLD, NEW = "p-apyr-us", "machines-on-machines"
SOURCE_API, TARGET_API = "srcapi", "dstapi"
SOURCE_BUCKET = "amplify-srcapp-mai-papyrusmediabucket-aaaa"
TARGET_BUCKET = "amplify-dstapp-mai-papyrusmediabucket-bbbb"
SUB = "-".join(["11111111", "2222", "3333", "4444", "555555555555"])


def make_table(client, model, api):
    client.create_table(
        TableName=f"{model}-{api}-NONE",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


def put(client, model, api, **attrs):
    item = {key: {"S": value} for key, value in attrs.items()}
    item["__typename"] = {"S": model}
    client.put_item(TableName=f"{model}-{api}-NONE", Item=item)


METADATA = {"M": {
    "classifier": {"S": f"{OLD}-relevance"}, "cyclotronId": {"S": "shared-source-relevance-r2"},
    "provenance": {"M": {"accountId": {"S": "acct-1"}, "runId": {"S": "run-1"}, "bindingId": {"S": f"bind-{OLD}"},
                         "bindingRevision": {"S": "4"}, "output": {"S": f"{OLD}-relevance"},
                         "publicationId": {"S": OLD}}}}}


@pytest.fixture
def world():
    with mock_aws():
        dynamodb = boto3.client("dynamodb", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        for model in ("Reference", "Item", "NewsroomSection", "Assignment", "ModelAttachment", "SemanticRelation"):
            make_table(dynamodb, model, SOURCE_API)
            make_table(dynamodb, model, TARGET_API)
        for bucket in (SOURCE_BUCKET, TARGET_BUCKET):
            s3.create_bucket(Bucket=bucket)
        put(dynamodb, "Reference", SOURCE_API, id="reference-knowledge-corpus-ai-ml-research-a-v1",
            discoveredByMonitorId=f"web-{OLD}", createdAt="2026-01-01T00:00:00Z", updatedAt="2026-01-02T00:00:00Z")
        put(dynamodb, "Item", SOURCE_API, id=f"{OLD}.item-x", tenantId=OLD, tenantSlug=f"{OLD}#x",
            sectionStatus=f"{OLD}#methods#draft", updatedAt="2026-01-02T00:00:00Z", versionCreatedBy=SUB)
        put(dynamodb, "NewsroomSection", SOURCE_API, id=f"{OLD}#security", tenantId=OLD)
        put(dynamodb, "Assignment", SOURCE_API, id=f"assignment-{OLD}-relevance-v2", queueKey=f"q#knowledge-corpus-{OLD}",
            createdBy="papyrus-cli")
        put(dynamodb, "ModelAttachment", SOURCE_API, id=f"model-attachment-{OLD}-m",
            storagePath=f"newsroom/payloads/assignmentevent/{OLD}-relevance/metadata.json")
        s3.put_object(Bucket=SOURCE_BUCKET, Key=f"newsroom/payloads/assignmentevent/{OLD}-relevance/metadata.json", Body=b"{}")
        s3.put_object(Bucket=SOURCE_BUCKET, Key="corpora/shared/a.pdf", Body=b"pdf")
        s3.put_object(Bucket=SOURCE_BUCKET, Key=f"cyclotrons/{OLD}-relevance-v2/state.tar.gz", Body=b"state")
        dynamodb.put_item(TableName=f"SemanticRelation-{SOURCE_API}-NONE", Item={
            "id": {"S": "semantic-relation-1"}, "__typename": {"S": "SemanticRelation"},
            "classifierId": {"S": f"{OLD}-relevance/{OLD}-relevance"}, "publicationId": {"S": OLD},
            "primeId": {"S": f"prime-{OLD}"}, "metadata": METADATA})
        yield dynamodb, s3


def copier(world, **overrides):
    dynamodb, s3 = world
    config = CopyConfig(from_api=SOURCE_API, to_api=TARGET_API, key_map={OLD: NEW},
                        from_bucket=SOURCE_BUCKET, to_bucket=TARGET_BUCKET, **overrides)
    return SiteCopier(config, dynamodb, dynamodb, s3, s3)


def target_ids(dynamodb, model):
    return sorted(i["id"]["S"] for i in dynamodb.scan(TableName=f"{model}-{TARGET_API}-NONE")["Items"])


def test_dry_run_writes_nothing(world):
    plan = copier(world, keep_unmapped_owners=True).run(apply=False)
    assert plan.ok and not plan.applied
    assert target_ids(world[0], "Item") == []
    assert world[1].list_objects_v2(Bucket=TARGET_BUCKET).get("KeyCount") == 0


def test_apply_rewrites_key_and_keeps_reference_ids(world):
    plan = copier(world, keep_unmapped_owners=True).run(apply=True)
    assert plan.ok and plan.applied
    dynamodb = world[0]
    assert target_ids(dynamodb, "Item") == [f"{NEW}.item-x"]
    assert target_ids(dynamodb, "NewsroomSection") == [f"{NEW}#security"]
    assert target_ids(dynamodb, "Reference") == ["reference-knowledge-corpus-ai-ml-research-a-v1"]
    reference = dynamodb.scan(TableName=f"Reference-{TARGET_API}-NONE")["Items"][0]
    assert reference["discoveredByMonitorId"]["S"] == f"web-{NEW}"
    assert reference["createdAt"]["S"] == "2026-01-01T00:00:00Z" and reference["__typename"]["S"] == "Reference"
    keys = {o["Key"] for o in world[1].list_objects_v2(Bucket=TARGET_BUCKET)["Contents"]}
    assert not any(key.startswith("cyclotrons/") for key in keys)
    assert keys == {f"newsroom/payloads/assignmentevent/{NEW}-relevance/metadata.json", "corpora/shared/a.pdf"}


def test_reference_id_embedding_the_key_stops_everything(world):
    put(world[0], "Reference", SOURCE_API, id=f"reference-knowledge-corpus-{OLD}-z")
    plan = copier(world, keep_unmapped_owners=True).run(apply=True)
    assert not plan.ok and not plan.applied
    assert any("Reference id" in r.reason for r in plan.refusals)
    assert target_ids(world[0], "Item") == []


def test_unlisted_id_field_with_key_is_refused(world):
    put(world[0], "Item", SOURCE_API, id="other", lineageId="x", itemId=f"{OLD}.item-x")
    plan = copier(world).run()
    assert any("no rewrite rule" in r.reason for r in plan.refusals)


def test_unmapped_sub_blocks_and_mapping_or_keep_resolves(world):
    assert not copier(world).run(apply=True).ok
    owner_map = {SUB: SUB.replace("11111111", "99999999")}
    assert copier(world, owner_map=owner_map).run(apply=True).ok
    item = world[0].get_item(TableName=f"Item-{TARGET_API}-NONE", Key={"id": {"S": f"{NEW}.item-x"}})["Item"]
    assert item["versionCreatedBy"]["S"] == owner_map[SUB]


def test_keep_unmapped_owners_is_reported_not_silent(world):
    plan = copier(world, keep_unmapped_owners=True).run()
    assert plan.ok
    item_report = next(r for r in plan.models if r.model == "Item")
    assert item_report.unmapped_owners == {SUB: 1}


def test_rerun_is_idempotent_and_target_newer_is_kept(world):
    first = copier(world)
    first.config.keep_unmapped_owners = True
    first.run(apply=True)
    second = first.run(apply=True)
    assert all(r.created == 0 and r.updated == 0 and r.written == 0 for r in second.models)
    assert second.media.copied == 0 and second.media.already_present == second.media.source_objects
    world[0].update_item(TableName=f"Item-{TARGET_API}-NONE", Key={"id": {"S": f"{NEW}.item-x"}},
                         UpdateExpression="SET title = :t, updatedAt = :u",
                         ExpressionAttributeValues={":t": {"S": "edited"}, ":u": {"S": "2026-02-01T00:00:00Z"}})
    third = first.run(apply=True)
    assert next(r for r in third.models if r.model == "Item").conflicts == 1


def test_verify_matches_then_detects_drift(world):
    c = copier(world)
    c.config.keep_unmapped_owners = True
    c.run(apply=True)
    assert c.verify().ok
    world[0].delete_item(TableName=f"Item-{TARGET_API}-NONE", Key={"id": {"S": f"{NEW}.item-x"}})
    bad = c.verify()
    assert not bad.ok and next(v for v in bad.verify if v["model"] == "Item")["missing"] == 1


def test_target_missing_table_is_an_error(world):
    world[0].delete_table(TableName=f"Assignment-{TARGET_API}-NONE")
    plan = copier(world).run()
    assert any("no table in the target" in e for e in plan.errors)


def test_models_subset_and_unknown_model(world):
    plan = copier(world, models=["NewsroomSection"]).run(apply=True)
    assert [r.model for r in plan.models] == ["NewsroomSection"]
    with pytest.raises(SiteCopyError):
        copier(world, models=["Nope"]).run()


def test_parse_key_map_rejects_bad_input():
    assert parse_key_map("a=b") == {"a": "b"}
    with pytest.raises(SiteCopyError):
        parse_key_map("nope")


def test_cli_defaults_to_dry_run_and_requires_apply(world, capsys, monkeypatch):
    factory = lambda profile, region: boto3.Session(region_name=region)
    args = ["--from-api", SOURCE_API, "--to-api", TARGET_API, "--corpus-key-map", f"{OLD}={NEW}",
            "--keep-unmapped-owners", "--json"]
    assert site_copy(args, factory) == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert target_ids(world[0], "Item") == []
    assert site_copy(args + ["--apply"], factory) == 0
    assert target_ids(world[0], "Item") == [f"{NEW}.item-x"]
    with pytest.raises(SiteCopyError):
        site_copy(args + ["--apply", "--dry-run"], factory)


def test_tables_by_model_finds_suffix(world):
    assert tables_by_model(world[0], SOURCE_API)["Item"] == f"Item-{SOURCE_API}-NONE"


def relation(dynamodb, api):
    return dynamodb.get_item(TableName=f"SemanticRelation-{api}-NONE", Key={"id": {"S": "semantic-relation-1"}})["Item"]


def test_classifier_field_is_rewritten_and_metadata_blob_is_byte_identical(world):
    copier(world, keep_unmapped_owners=True).run(apply=True)
    copied = relation(world[0], TARGET_API)
    assert copied["classifierId"]["S"] == f"{NEW}-relevance/{NEW}-relevance"
    assert copied["metadata"] == METADATA
    assert copied["publicationId"]["S"] == NEW


def test_cyclotron_provenance_ids_are_never_rewritten_even_in_rewritten_fields(world):
    from .site_copy import CYCLOTRON_PROTECTED_KEYS, map_strings_protected

    echoed = {"M": {"outer": {"S": f"{OLD}-x"}, "provenance": {"M": {
        "accountId": {"S": f"{OLD}-acct"}, "runId": {"S": f"{OLD}-run"}, "bindingId": {"S": f"{OLD}-b"},
        "bindingRevision": {"S": f"{OLD}-4"}}}}}
    result = map_strings_protected(echoed, lambda text: text.replace(OLD, NEW), CYCLOTRON_PROTECTED_KEYS)
    assert result["M"]["outer"]["S"] == f"{NEW}-x"
    assert result["M"]["provenance"] == echoed["M"]["provenance"]


def test_prime_list_id_is_untouched(world):
    copier(world, keep_unmapped_owners=True).run(apply=True)
    assert relation(world[0], TARGET_API)["primeId"]["S"] == f"prime-{OLD}"
    assert copier(world).rewriter.rewrite_key(f"prime-{OLD} and {OLD}-relevance") == f"prime-{OLD} and {NEW}-relevance"


def test_cyclotrons_prefix_is_skipped_by_default_and_counted(world):
    plan = copier(world, keep_unmapped_owners=True).run()
    assert plan.media.skipped_objects == 1 and plan.media.skipped_prefixes == ["cyclotrons/"]
    copier(world, keep_unmapped_owners=True).run(apply=True)
    assert c_verify_ok(world)


def c_verify_ok(world):
    c = copier(world, keep_unmapped_owners=True)
    return c.verify().verify_media["match"]


def test_skip_media_prefix_flag_is_repeatable_and_replaces_the_default(world, capsys):
    factory = lambda profile, region: boto3.Session(region_name=region)
    base = ["--from-api", SOURCE_API, "--to-api", TARGET_API, "--corpus-key-map", f"{OLD}={NEW}",
            "--from-media-bucket", SOURCE_BUCKET, "--to-media-bucket", TARGET_BUCKET, "--keep-unmapped-owners", "--json"]
    site_copy(base, factory)
    assert json.loads(capsys.readouterr().out)["media"]["skipped_prefixes"] == ["cyclotrons/"]
    site_copy(base + ["--skip-media-prefix", "corpora/", "--skip-media-prefix", "newsroom/"], factory)
    media = json.loads(capsys.readouterr().out)["media"]
    assert media["skipped_prefixes"] == ["corpora/", "newsroom/"] and media["skipped_objects"] == 2
    site_copy(base + ["--skip-media-prefix", "none"], factory)
    assert json.loads(capsys.readouterr().out)["media"]["skipped_objects"] == 0
