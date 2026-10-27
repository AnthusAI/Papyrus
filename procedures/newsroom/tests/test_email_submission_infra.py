from pathlib import Path

import yaml


class CloudFormationLoader(yaml.SafeLoader):
    pass


def tagged(loader, tag, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        value = loader.construct_mapping(node)
    return {tag: value}


CloudFormationLoader.add_multi_constructor("!", tagged)


def test_submission_receipt_preserves_ses_authority_and_separates_legacy_commands():
    path = Path(__file__).resolve().parents[3] / "infra/email/papyrus-email-submissions.yaml"
    template = yaml.load(path.read_text(), Loader=CloudFormationLoader)
    resources = template["Resources"]
    kinds = [r["Type"] for r in resources.values()]
    assert "AWS::SES::ReceiptRuleSet" not in kinds
    assert "AWS::SES::EmailIdentity" not in kinds
    assert "AWS::Route53::RecordSet" not in kinds
    assert "Custom::AWS" not in kinds
    assert template["Parameters"]["Enabled"]["Default"] == "false"
    rule = resources["SubmissionRule"]["Properties"]
    assert rule["RuleSetName"] == {"Ref": "ExistingReceiptRuleSetName"}
    assert [next(iter(a)) for a in rule["Rule"]["Actions"]] == ["S3Action", "LambdaAction", "StopAction"]
    assert rule["Rule"]["Actions"][0]["S3Action"]["ObjectKeyPrefix"] == "email-submissions/"
    assert rule["Rule"]["Actions"][1]["LambdaAction"]["InvocationType"] == "Event"
    assert rule["Rule"]["ScanEnabled"] is True
    assert rule["Rule"]["TlsPolicy"] == "Require"
    worker = resources["SubmissionFunction"]["Properties"]
    assert worker["Handler"] == "papyrus_content.email_submission_intake.handler"
    assert worker["Timeout"] == 120
    assert worker["ReservedConcurrentExecutions"] == {"If": ["ReserveConcurrency", {"Ref": "ReservedConcurrency"}, {"Ref": "AWS::NoValue"}]}
    assert worker["Environment"]["Variables"]["EMAIL_RAW_PREFIX"] == "email-submissions/"
    assert worker["DeadLetterConfig"]["TargetArn"] == {"GetAtt": "FailureQueue.Arn"}
    assert resources["RawMailBucket"]["Properties"]["PublicAccessBlockConfiguration"]["BlockPublicPolicy"] is True
    policy = resources["SubmissionRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    table = next(s for s in policy if "dynamodb:GetItem" in s["Action"])
    assert table["Condition"]["ForAllValues:StringEquals"]["dynamodb:LeadingKeys"] == [{"Sub": "MONITOR#${MonitorId}"}]
    manifest = next(s for s in policy if "s3:PutObject" in s["Action"])
    assert manifest["Resource"] == {"Sub": "${RawMailBucket.Arn}/email-submissions/manifests/*"}
    table_arn = "arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${MonitoringTableName}"
    queries = {s["Resource"]["Sub"]: s for s in policy if "dynamodb:Query" in s["Action"]}
    assert set(queries) == {table_arn + "/index/routing", table_arn}
    index = queries[table_arn + "/index/routing"]
    assert index["Condition"]["ForAllValues:StringEquals"]["dynamodb:LeadingKeys"] == [
        {"Sub": "EMAIL_PENDING#${MonitorId}"}, {"Sub": "EMAIL_ACTION#${MonitorId}"}]
    # Quarantine reads stay inside the one receiver partition.
    partition = queries[table_arn]
    assert partition["Condition"]["ForAllValues:StringEquals"]["dynamodb:LeadingKeys"] == [{"Sub": "MONITOR#${MonitorId}"}]
    assert not any(any(a.startswith(("ses:", "appsync:", "sts:", "lambda:")) for a in s["Action"]) for s in policy)
    assert resources["SesInvokePermission"]["Properties"]["SourceAccount"] == {"Ref": "AWS::AccountId"}
    assert "FailureAlarm" in resources
    assert template["Parameters"]["RouterEnabled"]["Default"] == "false"
    schedule = resources["RouterSchedule"]["Properties"]
    assert schedule["ScheduleExpression"] == "rate(5 minutes)"
    assert schedule["Targets"][0]["Arn"] == {"Ref": "RouterFunctionArn"}
    assert schedule["Targets"][0]["Input"] == {"Sub": '{"monitorId":"${MonitorId}"}'}
    assert resources["RouterInvokePermission"]["Properties"]["SourceArn"] == {"GetAtt": "RouterSchedule.Arn"}
    resume = resources["EmailResumeSchedule"]["Properties"]
    assert resume["ScheduleExpression"] == "rate(1 minute)"
    assert resume["State"] == {"If": ["EnableReceipt", "ENABLED", "DISABLED"]}
    assert resume["Targets"][0]["Input"] == {"Sub": '{"task":"resume","monitorId":"${MonitorId}"}'}
    assert resources["EmailResumeInvokePermission"]["Properties"]["SourceArn"] == {"GetAtt": "EmailResumeSchedule.Arn"}


def test_membership_permissions_are_read_only_and_limited_to_explicit_pools():
    email_path = Path(__file__).resolve().parents[3] / "infra/email/papyrus-email-submissions.yaml"
    email_template = yaml.load(email_path.read_text(), Loader=CloudFormationLoader)
    assert email_template["Conditions"]["HasEditorUserPools"] == {
        "Not": [{"Equals": [{"Join": ["", {"Ref": "EditorUserPoolArns"}]}, ""]}]}
    email_policy = email_template["Resources"]["SubmissionEditorMembershipPolicy"]
    assert email_policy["Condition"] == "HasEditorUserPools"
    email_grant = email_policy["Properties"]["PolicyDocument"]["Statement"][0]
    assert set(email_grant["Action"]) == {"cognito-idp:ListUsers", "cognito-idp:AdminListGroupsForUser"}
    assert email_grant["Resource"] == {"Ref": "EditorUserPoolArns"}

    router_path = Path(__file__).resolve().parents[3] / "infra/monitoring/papyrus-monitoring.yaml"
    router_template = yaml.load(router_path.read_text(), Loader=CloudFormationLoader)
    router_policy = router_template["Resources"]["RouterEditorMembershipPolicy"]
    assert router_policy["Condition"] == "HasEditorUserPools"
    grant = router_policy["Properties"]["PolicyDocument"]["Statement"][0]
    assert grant["Sid"] == "EmailEditorMembership"
    assert set(grant["Action"]) == {"cognito-idp:ListUsers", "cognito-idp:AdminListGroupsForUser"}
    assert grant["Resource"] == {"Ref": "EditorUserPoolArns"}


def test_receiver_can_rely_on_its_durable_lease_when_account_cannot_reserve_concurrency():
    path = Path(__file__).resolve().parents[3] / "infra/email/papyrus-email-submissions.yaml"
    template = yaml.load(path.read_text(), Loader=CloudFormationLoader)
    parameter = template["Parameters"]["ReservedConcurrency"]
    assert parameter["Default"] == 1
    assert parameter["AllowedValues"] == [0, 1]
    assert template["Conditions"]["ReserveConcurrency"] == {"Equals": [{"Ref": "ReservedConcurrency"}, 1]}


def test_receiving_rule_set_is_account_owned_inactive_and_retained():
    path = Path(__file__).resolve().parents[3] / "infra/email/papyrus-email-receiving-set.yaml"
    template = yaml.load(path.read_text(), Loader=CloudFormationLoader)
    resources = template["Resources"]
    assert list(resources) == ["PapyrusEmailReceivingRuleSet"]
    rule_set = resources["PapyrusEmailReceivingRuleSet"]
    assert rule_set["Type"] == "AWS::SES::ReceiptRuleSet"
    assert rule_set["Properties"]["RuleSetName"] == {"Ref": "ReceiptRuleSetName"}
    assert rule_set["DeletionPolicy"] == "Retain"
    assert rule_set["UpdateReplacePolicy"] == "Retain"
    assert template["Parameters"]["ReceiptRuleSetName"]["Default"] == "papyrus-email-receiving"
    assert not any(r["Type"] in {"AWS::SES::ReceiptRule", "AWS::SES::EmailIdentity", "AWS::Route53::RecordSet"} for r in resources.values())
