from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from behave import given, then, when

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

from papyrus_content.site_copy import SiteCopyError  # noqa: E402
from papyrus_content.site_copy_commands import site_copy  # noqa: E402

OLD, NEW = "p-apyr-us", "machines-on-machines"
SRC, DST = "srcapi", "dstapi"
SRC_BUCKET = "amplify-srcapp-mai-papyrusmediabucket-aaaa"
DST_BUCKET = "amplify-dstapp-mai-papyrusmediabucket-bbbb"
SUB = "-".join(["11111111", "2222", "3333", "4444", "555555555555"])
NEW_SUB = "-".join(["99999999", "2222", "3333", "4444", "555555555555"])
MODELS = ("Reference", "Item", "NewsroomSection", "Assignment", "ModelAttachment", "SemanticRelation")
METADATA = {"M": {
    "classifier": {"S": f"{OLD}-relevance"}, "cyclotronId": {"S": "shared-source-relevance-r2"},
    "provenance": {"M": {"accountId": {"S": "acct-1"}, "runId": {"S": "run-1"}, "bindingId": {"S": f"bind-{OLD}"},
                         "bindingRevision": {"S": "4"}, "output": {"S": f"{OLD}-relevance"}, "publicationId": {"S": OLD}}}}}
PAYLOAD = f"newsroom/payloads/assignmentevent/{OLD}-relevance/metadata.json"


def put(db, model, api, **attrs):
    item = {key: {"S": value} for key, value in attrs.items()}
    item["__typename"] = {"S": model}
    db.put_item(TableName=f"{model}-{api}-NONE", Item=item)


def ids(db, model):
    return sorted(i["id"]["S"] for i in db.scan(TableName=f"{model}-{DST}-NONE")["Items"])


def run(context, *extra, owner_map=False):
    args = ["--from-api", SRC, "--to-api", DST, "--corpus-key-map", f"{OLD}={NEW}",
            "--from-media-bucket", SRC_BUCKET, "--to-media-bucket", DST_BUCKET, "--json", *extra]
    if owner_map:
        path = Path(context.tmp) / "owners.json"
        path.write_text(json.dumps({SUB: NEW_SUB}))
        args += ["--owner-map", str(path)]
    context.error = None
    context.out = ""
    try:
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            context.code = site_copy(args, lambda profile, region: boto3.Session(region_name=region))
        context.out = buffer.getvalue()
        context.report = json.loads(context.out)
    except SiteCopyError as error:
        context.error = error
        context.report = None


@given("a source site backend holding records of the site p-apyr-us")
def step_source(context):
    import tempfile

    context.tmp = tempfile.mkdtemp()
    context.mock = mock_aws()
    context.mock.start()
    context.db = boto3.client("dynamodb", region_name="us-east-1")
    context.s3 = boto3.client("s3", region_name="us-east-1")
    for model in MODELS:
        for api in (SRC, DST):
            context.db.create_table(
                TableName=f"{model}-{api}-NONE",
                KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
    for bucket in (SRC_BUCKET, DST_BUCKET):
        context.s3.create_bucket(Bucket=bucket)
    db = context.db
    put(db, "Reference", SRC, id="reference-knowledge-corpus-ai-ml-research-a-v1", discoveredByMonitorId=f"web-{OLD}",
        createdAt="2026-01-01T00:00:00Z", updatedAt="2026-01-02T00:00:00Z")
    put(db, "Item", SRC, id=f"{OLD}.item-x", tenantId=OLD, tenantSlug=f"{OLD}#x", sectionStatus=f"{OLD}#methods#draft",
        updatedAt="2026-01-02T00:00:00Z", versionCreatedBy=SUB, createdBy="papyrus-cli")
    put(db, "NewsroomSection", SRC, id=f"{OLD}#security", tenantId=OLD)
    put(db, "Assignment", SRC, id=f"assignment-{OLD}-relevance-v2", queueKey=f"q#knowledge-corpus-{OLD}")
    put(db, "ModelAttachment", SRC, id=f"model-attachment-{OLD}-m", storagePath=PAYLOAD)
    context.s3.put_object(Bucket=SRC_BUCKET, Key=PAYLOAD, Body=b"{}")
    context.s3.put_object(Bucket=SRC_BUCKET, Key="corpora/shared/a.pdf", Body=b"pdf")
    context.s3.put_object(Bucket=SRC_BUCKET, Key=f"cyclotrons/{OLD}-relevance-v2/state.tar.gz", Body=b"state")
    db.put_item(TableName=f"SemanticRelation-{SRC}-NONE", Item={
        "id": {"S": "semantic-relation-1"}, "__typename": {"S": "SemanticRelation"},
        "classifierId": {"S": f"{OLD}-relevance/{OLD}-relevance"}, "publicationId": {"S": OLD},
        "primeId": {"S": f"prime-{OLD}"}, "metadata": METADATA})
    context.add_cleanup(context.mock.stop)


@given("an empty target site backend with the same tables")
def step_target(context):
    pass


@given("a source Reference whose id embeds the corpus key")
def step_bad_reference(context):
    put(context.db, "Reference", SRC, id=f"reference-knowledge-corpus-{OLD}-z")


@given("a source Item with an unlisted foreign-key field that embeds the corpus key")
def step_bad_foreign_key(context):
    put(context.db, "Item", SRC, id="other", sectionId=f"{OLD}#security")


@given("I have run the site copy with --apply")
def step_applied(context):
    run(context, "--apply", owner_map=True)
    assert context.code == 0, context.out


@when("I run the site copy without --apply")
def step_dry(context):
    run(context, owner_map=True)


@when("I run the site copy with --apply and --dry-run")
def step_both(context):
    run(context, "--apply", "--dry-run")


@when("I run the site copy with --apply")
def step_apply(context):
    run(context, "--apply", owner_map=True)


@when("I run the site copy with --apply and no owner map")
def step_apply_unmapped(context):
    run(context, "--apply")


@when("I run the site copy with --apply and an owner map for that sub")
def step_apply_mapped(context):
    run(context, "--apply", owner_map=True)


@when("I run the site copy with --verify")
def step_verify(context):
    run(context, "--verify", owner_map=True)


@when("a copied record is deleted from the target")
def step_delete(context):
    context.db.delete_item(TableName=f"Item-{DST}-NONE", Key={"id": {"S": f"{NEW}.item-x"}})


@then("the report counts the source records per model")
def step_counts(context):
    counts = {m["model"]: m["source"] for m in context.report["models"]}
    assert counts["Item"] == 1 and counts["Reference"] == 1, counts
    assert context.report["applied"] is False


@then("the target tables hold no records")
def step_empty_tables(context):
    assert all(ids(context.db, model) == [] for model in MODELS)


@then("the target bucket holds no objects")
def step_empty_bucket(context):
    assert context.s3.list_objects_v2(Bucket=DST_BUCKET).get("KeyCount") == 0


@then("the command is refused before anything is read")
def step_refused_flags(context):
    assert context.error is not None and "not both" in str(context.error)


@then('the Item "p-apyr-us.item-x" is in the target as "machines-on-machines.item-x"')
def step_item(context):
    assert ids(context.db, "Item") == [f"{NEW}.item-x"]


@then('the Section "p-apyr-us#security" is in the target as "machines-on-machines#security"')
def step_section(context):
    assert ids(context.db, "NewsroomSection") == [f"{NEW}#security"]


@then("the Assignment queue key names the new corpus")
def step_queue(context):
    item = context.db.scan(TableName=f"Assignment-{DST}-NONE")["Items"][0]
    assert item["queueKey"]["S"] == f"q#knowledge-corpus-{NEW}"


@then("the report lists the rewrite counts per rule and a sample of before and after ids")
def step_report(context):
    item = next(m for m in context.report["models"] if m["model"] == "Item")
    assert item["rewrites"]["corpus-key"] >= 3
    assert item["samples"][0] == {"before": f"{OLD}.item-x", "after": f"{NEW}.item-x"}


@then("timestamps and __typename are unchanged")
def step_preserved(context):
    item = context.db.get_item(TableName=f"Item-{DST}-NONE", Key={"id": {"S": f"{NEW}.item-x"}})["Item"]
    assert item["updatedAt"]["S"] == "2026-01-02T00:00:00Z" and item["__typename"]["S"] == "Item"


@then("the Reference id is identical in the target")
def step_ref_same(context):
    assert ids(context.db, "Reference") == ["reference-knowledge-corpus-ai-ml-research-a-v1"]


@then("only its discovering monitor id is rewritten")
def step_ref_monitor(context):
    item = context.db.scan(TableName=f"Reference-{DST}-NONE")["Items"][0]
    assert item["discoveredByMonitorId"]["S"] == f"web-{NEW}"


@then("the copy is refused and names that Reference")
def step_refused_reference(context):
    reasons = [r for r in context.report["models"] if r["model"] == "Reference"][0]["refusals"]
    assert context.code == 1 and any("Reference id" in r["reason"] for r in reasons)


@then("the report refuses it as an id that cannot be mapped")
def step_refused_unmapped_id(context):
    item = next(m for m in context.report["models"] if m["model"] == "Item")
    assert any("cannot be mapped" in r["reason"] for r in item["refusals"])


@then("the copy is refused and the unmapped Cognito sub is listed")
def step_unmapped_sub(context):
    item = next(m for m in context.report["models"] if m["model"] == "Item")
    assert context.code == 1
    assert item["unmapped_owners"] == {SUB: 1}


@then("the target record carries the new sub")
def step_new_sub(context):
    item = context.db.get_item(TableName=f"Item-{DST}-NONE", Key={"id": {"S": f"{NEW}.item-x"}})["Item"]
    assert item["versionCreatedBy"]["S"] == NEW_SUB


@then("service names and emails in owner fields are kept and counted")
def step_owner_classes(context):
    item = next(m for m in context.report["models"] if m["model"] == "Item")
    assert item["owner_classes"]["createdBy: service name (kept)"] == 1


@then("every source object is in the target bucket")
def step_objects(context):
    keys = {o["Key"] for o in context.s3.list_objects_v2(Bucket=DST_BUCKET)["Contents"]}
    assert "corpora/shared/a.pdf" in keys and len(keys) == 2, keys


@then("the payload key that embedded p-apyr-us carries machines-on-machines")
def step_payload_key(context):
    keys = {o["Key"] for o in context.s3.list_objects_v2(Bucket=DST_BUCKET)["Contents"]}
    assert PAYLOAD.replace(OLD, NEW) in keys and PAYLOAD not in keys


@then("no record is created or updated and no object is copied")
def step_nothing(context):
    assert all(m["created"] == 0 and m["updated"] == 0 and m["written"] == 0 for m in context.report["models"])
    assert context.report["media"]["copied"] == 0


@then("a target record edited later is kept and reported, not overwritten")
def step_kept(context):
    context.db.update_item(TableName=f"Item-{DST}-NONE", Key={"id": {"S": f"{NEW}.item-x"}},
                           UpdateExpression="SET title = :t, updatedAt = :u",
                           ExpressionAttributeValues={":t": {"S": "edited"}, ":u": {"S": "2026-02-01T00:00:00Z"}})
    run(context, "--apply", owner_map=True)
    item = next(m for m in context.report["models"] if m["model"] == "Item")
    assert item["conflicts"] == 1 and item["written"] == 0


@then("every model matches on count and content hash")
def step_verify_ok(context):
    assert context.code == 0 and all(v["match"] for v in context.report["verify"])


@then("the verification reports it as missing and fails")
def step_verify_bad(context):
    item = next(v for v in context.report["verify"] if v["model"] == "Item")
    assert context.code == 1 and item["missing"] == 1


def copied_relation(context):
    return context.db.get_item(TableName=f"SemanticRelation-{DST}-NONE", Key={"id": {"S": "semantic-relation-1"}})["Item"]


@then("the relation's own classifier field names machines-on-machines-relevance")
def step_classifier(context):
    assert copied_relation(context)["classifierId"]["S"] == f"{NEW}-relevance/{NEW}-relevance"
    assert copied_relation(context)["publicationId"]["S"] == NEW


@then("the relation's provenance metadata blob is identical to the source")
def step_blob(context):
    assert copied_relation(context)["metadata"] == METADATA


@then("the priming list id prime-p-apyr-us is unchanged")
def step_prime(context):
    assert copied_relation(context)["primeId"]["S"] == f"prime-{OLD}"


@then("the cyclotrons/ prefix is skipped and the skipped objects are counted")
def step_skip(context):
    keys = {o["Key"] for o in context.s3.list_objects_v2(Bucket=DST_BUCKET)["Contents"]}
    assert not any(key.startswith("cyclotrons/") for key in keys)
    assert context.report["media"]["skipped_objects"] == 1
    assert context.report["media"]["skipped_prefixes"] == ["cyclotrons/"]


@when("I run the site copy skipping the corpora/ prefix instead")
def step_skip_flag(context):
    run(context, "--skip-media-prefix", "corpora/")


@then("the corpora/ objects are skipped and the cyclotrons/ state is copied")
def step_skip_flag_result(context):
    assert context.report["media"]["skipped_prefixes"] == ["corpora/"]
    assert context.report["media"]["skipped_objects"] == 1
