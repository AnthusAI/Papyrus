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
    assert worker["ReservedConcurrentExecutions"] == 1
    assert worker["Environment"]["Variables"]["EMAIL_RAW_PREFIX"] == "email-submissions/"
    assert worker["DeadLetterConfig"]["TargetArn"] == {"GetAtt": "FailureQueue.Arn"}
    assert resources["RawMailBucket"]["Properties"]["PublicAccessBlockConfiguration"]["BlockPublicPolicy"] is True
    policy = resources["SubmissionRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    table = next(s for s in policy if "dynamodb:GetItem" in s["Action"])
    assert table["Condition"]["ForAllValues:StringEquals"]["dynamodb:LeadingKeys"] == [{"Sub": "MONITOR#${MonitorId}"}]
    assert not any(any(a.startswith(("ses:", "appsync:", "sts:", "lambda:")) for a in s["Action"]) for s in policy)
    assert resources["SesInvokePermission"]["Properties"]["SourceAccount"] == {"Ref": "AWS::AccountId"}
    assert "FailureAlarm" in resources
    assert template["Parameters"]["RouterEnabled"]["Default"] == "false"
    schedule = resources["RouterSchedule"]["Properties"]
    assert schedule["ScheduleExpression"] == "rate(5 minutes)"
    assert schedule["Targets"][0]["Arn"] == {"Ref": "RouterFunctionArn"}
    assert schedule["Targets"][0]["Input"] == {"Sub": '{"monitorId":"${MonitorId}"}'}
    assert resources["RouterInvokePermission"]["Properties"]["SourceArn"] == {"GetAtt": "RouterSchedule.Arn"}
