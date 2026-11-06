"""The operator alert listener (PPY-e92c8e, PPY-dd8c18): template, IAM, catalog, build and the path to a real-looking email.

The template and the catalog are read as data. The email scenarios use the caducus package when it is importable
(PYTHONPATH to a Caducus checkout, or the pinned wheel); without it they skip.
"""
from __future__ import annotations

import importlib.util
import json
import re
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
MONITORING = ROOT / "infra" / "monitoring"
TEMPLATE = MONITORING / "papyrus-monitoring.yaml"
CATALOG = MONITORING / "alarm-catalog.yaml"
REQUIREMENT = MONITORING / "caducus-requirement.txt"
PREFIX = "papyrus-operator-"
TEST_ALARM = "papyrus-notify-test-alarm"
LEGACY_ALARMS = {"papyrus-monitoring-collector-errors", "papyrus-monitoring-search-provider-failing", "papyrus-monitoring-router-errors",
                 "papyrus-monitoring-router-dead-letters", "papyrus-monitoring-decisions-stopped"}


class Loader(yaml.SafeLoader):
    pass


def _tag(loader, suffix, node):
    value = (loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else
             loader.construct_sequence(node, deep=True) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node, deep=True))
    if suffix == "GetAtt" and isinstance(value, str):
        value = value.split(".", 1)
    return {suffix if suffix in ("Ref", "Condition") else f"Fn::{suffix}": value}


Loader.add_multi_constructor("!", _tag)


@pytest.fixture(scope="module")
def whole():
    return yaml.load(TEMPLATE.read_text(), Loader=Loader)


@pytest.fixture(scope="module")
def resources(whole):
    return whole["Resources"]


def of_type(resources, type_name):
    return {name: r for name, r in resources.items() if r["Type"] == type_name}


def statements(role):
    return [s for policy in role["Properties"]["Policies"] for s in policy["PolicyDocument"]["Statement"]]


def listify(value):
    return value if isinstance(value, list) else [value]


# --- the listener's pieces -------------------------------------------------------------------------------------------------------------

def test_every_alarm_state_change_on_the_default_bus_goes_to_the_ingest_queue_except_the_last_resort_alarms(resources):
    rule = resources["OperatorAlarmRule"]["Properties"]
    assert "EventBusName" not in rule   # the default bus
    pattern = rule["EventPattern"]
    assert pattern["source"] == ["aws.cloudwatch"] and pattern["detail-type"] == ["CloudWatch Alarm State Change"]
    assert pattern["detail"] == {"alarmName": [{"anything-but": {"prefix": PREFIX}}]}
    assert rule["Targets"][0]["Arn"] == {"Fn::GetAtt": ["OperatorIngestQueue", "Arn"]}
    policy = resources["OperatorIngestQueuePolicy"]["Properties"]["PolicyDocument"]["Statement"][0]
    assert policy["Principal"] == {"Service": "events.amazonaws.com"} and policy["Action"] == "sqs:SendMessage"
    assert policy["Condition"]["ArnEquals"]["aws:SourceArn"] == {"Fn::GetAtt": ["OperatorAlarmRule", "Arn"]}


def test_both_queues_have_dead_letter_queues_and_wait_longer_than_a_function_runs(resources):
    for queue, dead, consumer in (("OperatorIngestQueue", "OperatorIngestDeadLetterQueue", "OperatorRouterFunction"),
                                  ("OperatorEmailQueue", "OperatorEmailDeadLetterQueue", "OperatorEmailFunction")):
        props = resources[queue]["Properties"]
        assert props["RedrivePolicy"]["deadLetterTargetArn"] == {"Fn::GetAtt": [dead, "Arn"]} and props["RedrivePolicy"]["maxReceiveCount"] >= 3
        assert props["VisibilityTimeout"] >= 6 * resources[consumer]["Properties"]["Timeout"]
        assert props["SqsManagedSseEnabled"] is True
        assert resources[dead]["Properties"]["MessageRetentionPeriod"] == 1209600
    assert resources["OperatorIngestQueue"]["Properties"]["QueueName"] == "papyrus-operator-ingest"
    assert resources["OperatorEmailQueue"]["Properties"]["QueueName"] == "papyrus-operator-email"


def test_the_table_matches_what_caducus_stores(resources):
    table = resources["OperatorTable"]
    props = table["Properties"]
    assert props["TableName"] == "papyrus-operator-alerts"
    assert table["DeletionPolicy"] == table["UpdateReplacePolicy"] == "Retain"
    assert props["TimeToLiveSpecification"] == {"AttributeName": "expiresAt", "Enabled": True}
    assert props["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is False   # erasure is real
    assert props["SSESpecification"]["SSEEnabled"] is True and props["BillingMode"] == "PAY_PER_REQUEST"
    assert [k["AttributeName"] for k in props["KeySchema"]] == ["pk", "sk"]
    (index,) = props["GlobalSecondaryIndexes"]
    assert index["IndexName"] == "byRecipient" and [k["AttributeName"] for k in index["KeySchema"]] == ["recipientKey", "queuedAt"]


FUNCTIONS = {"OperatorRouterFunction": "router", "OperatorFlushFunction": "flush", "OperatorReconcileFunction": "reconcile",
             "OperatorEmailFunction": "email_sender", "OperatorSesEventsFunction": "ses_events"}


def test_each_function_runs_a_caducus_handler_from_the_operator_zip(resources, whole):
    assert whole["Parameters"]["OperatorCodeKey"]["Type"] == "String" and "Default" not in whole["Parameters"]["OperatorCodeKey"]
    for name, module in FUNCTIONS.items():
        props = resources[name]["Properties"]
        assert props["Handler"] == f"caducus.notify.handlers.{module}.handler"
        assert props["Runtime"] == "python3.13" and props["Architectures"] == ["arm64"]
        assert props["Code"] == {"S3Bucket": {"Ref": "CodeBucket"}, "S3Key": {"Ref": "OperatorCodeKey"}}
        assert "ReservedConcurrentExecutions" not in props   # accounts with a low concurrency quota cannot reserve any
    # the collector and router functions are untouched: their code keys are not the operator's
    assert resources["CollectorFunction"]["Properties"]["Code"]["S3Key"] == {"Ref": "CodeKey"}
    assert resources["RouterFunction"]["Properties"]["Code"]["S3Key"] == {"Ref": "RouterCodeKey"}


def test_the_functions_get_their_settings_from_the_environment_and_never_an_address(resources, whole):
    wanted = {"TABLE_NAME", "OPERATORS_PARAMETER", "RECIPIENT_KEY_PARAMETER", "EMAIL_QUEUE_URL", "FROM_ADDRESS", "CONFIGURATION_SET",
              "TRIAGE_PARAMETER", "TRIAGE_ROLE_NAME", "CADUCUS_CONFIG_DIR", "METRIC_NAMESPACE"}
    for name in ("OperatorRouterFunction", "OperatorFlushFunction", "OperatorReconcileFunction", "OperatorEmailFunction"):
        env = resources[name]["Properties"]["Environment"]["Variables"]
        assert wanted <= set(env), (name, wanted - set(env))
        assert env["CADUCUS_CONFIG_DIR"] == "/var/task/config" and env["METRIC_NAMESPACE"] == "Papyrus/Operator"
        assert env["FROM_ADDRESS"] == {"Fn::Sub": "alerts@${OperatorSendingDomain}"}
        assert env["OPERATORS_PARAMETER"] == {"Ref": "OperatorsParameterName"}
        assert env["TRIAGE_ROLE_NAME"] == {"Ref": "TriageRoleName"}
    parameters = whole["Parameters"]
    assert parameters["OperatorsParameterName"]["Default"] == "/papyrus/shipped/knowledge-run/alarm-email"   # decision C
    assert parameters["TriageRoleName"]["Default"] == "AdministratorAccess"   # configuration, not code: a read-only set can replace it
    assert parameters["TriageParameterName"]["Default"] == "/papyrus/monitoring/triage"
    assert parameters["OperatorSendingDomain"]["Default"] == "notify.anth.us" and parameters["OperatorConfigurationSet"]["Default"] == "papyrus-operators"
    assert resources["OperatorReconcileFunction"]["Properties"]["Environment"]["Variables"]["IGNORE_ALARM_PREFIXES"] == PREFIX
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", TEMPLATE.read_text())


def test_the_queues_feed_the_functions_with_partial_batch_failures(resources):
    ingest, email = resources["OperatorIngestMapping"]["Properties"], resources["OperatorEmailMapping"]["Properties"]
    assert ingest["EventSourceArn"] == {"Fn::GetAtt": ["OperatorIngestQueue", "Arn"]} and ingest["FunctionName"] == {"Ref": "OperatorRouterFunction"}
    assert email["EventSourceArn"] == {"Fn::GetAtt": ["OperatorEmailQueue", "Arn"]} and email["FunctionName"] == {"Ref": "OperatorEmailFunction"}
    assert ingest["FunctionResponseTypes"] == email["FunctionResponseTypes"] == ["ReportBatchItemFailures"]
    assert email["ScalingConfig"]["MaximumConcurrency"] <= 2   # one SES rate shared with every site


def test_ses_events_of_the_operator_configuration_set_reach_the_ses_events_function(resources):
    rule = resources["OperatorSesEventsRule"]["Properties"]
    assert rule["EventPattern"] == {"source": ["aws.ses"], "detail": {"mail": {"tags": {"ses:configuration-set": [{"Ref": "OperatorConfigurationSet"}]}}}}
    assert rule["Targets"][0]["Arn"] == {"Fn::GetAtt": ["OperatorSesEventsFunction", "Arn"]}
    permission = resources["OperatorSesEventsPermission"]["Properties"]
    assert permission["Principal"] == "events.amazonaws.com" and permission["SourceArn"] == {"Fn::GetAtt": ["OperatorSesEventsRule", "Arn"]}


def test_the_recipient_key_is_created_once_by_a_custom_resource_and_kept(resources):
    key = resources["OperatorRecipientKey"]
    assert key["Type"] == "Custom::SecureStringParameter" and key["DeletionPolicy"] == "Retain"
    assert key["Properties"]["ParameterName"] == "/papyrus/monitoring/recipient-key"
    code = resources["OperatorRecipientKeyFunction"]["Properties"]["Code"]["ZipFile"]
    assert len(code) < 4096 and "Overwrite=False" in code and 'Type="SecureString"' in code and "ParameterAlreadyExists" in code
    assert "print(" not in code and "logging" not in code   # the value is never logged
    (grant,) = statements(resources["OperatorRecipientKeyRole"])
    assert grant["Action"] == "ssm:PutParameter" and grant["Resource"]["Fn::Sub"].endswith("parameter/papyrus/monitoring/recipient-key")
    for name in FUNCTIONS:
        assert "OperatorRecipientKey" in listify(resources[name].get("DependsOn", [])) or name == "OperatorSesEventsFunction"


# --- IAM -------------------------------------------------------------------------------------------------------------------------------

OPERATOR_ROLES = ("OperatorCoreRole", "OperatorEmailRole", "OperatorSesEventsRole", "OperatorScheduleRole", "OperatorRecipientKeyRole")
# The only grants that cannot name a resource, and why: DescribeAlarms and GetAccount have no resource-level permission; PutMetricData is
# limited by the cloudwatch:namespace condition instead.
WILDCARD_RESOURCE_ACTIONS = {"cloudwatch:DescribeAlarms", "ses:GetAccount", "cloudwatch:PutMetricData"}


def test_operator_roles_have_no_wildcard_actions_and_only_three_unnamed_resources(resources):
    seen = set()
    for role in OPERATOR_ROLES:
        for statement in statements(resources[role]):
            actions = listify(statement["Action"])
            assert all("*" not in a for a in actions), (role, actions)
            if "*" in listify(statement["Resource"]):
                assert set(actions) <= WILDCARD_RESOURCE_ACTIONS, (role, actions)
                seen |= set(actions)
                if actions == ["cloudwatch:PutMetricData"]:
                    assert statement["Condition"] == {"StringEquals": {"cloudwatch:namespace": "Papyrus/Operator"}}
    assert seen == WILDCARD_RESOURCE_ACTIONS


def test_email_is_sent_only_from_the_operator_identity_with_the_operator_configuration_set(resources):
    (send,) = [s for s in statements(resources["OperatorEmailRole"]) if s["Action"] == "ses:SendEmail"]
    assert send["Resource"] == [{"Fn::Sub": "arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:identity/${OperatorSendingDomain}"},
                                {"Fn::Sub": "arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:configuration-set/${OperatorConfigurationSet}"}]
    assert send["Condition"] == {"StringEquals": {"ses:FromAddress": {"Fn::Sub": "alerts@${OperatorSendingDomain}"}}}
    for role in OPERATOR_ROLES:
        if role != "OperatorEmailRole":
            assert not any("ses:" in a for s in statements(resources[role]) for a in listify(s["Action"])), role


def test_parameters_are_read_by_exact_name_and_nothing_else_is_decrypted(resources):
    for role in ("OperatorCoreRole", "OperatorEmailRole"):
        (read,) = [s for s in statements(resources[role]) if s["Action"] == "ssm:GetParameter"]
        names = [r["Fn::Sub"].split("parameter", 1)[1] for r in read["Resource"]]
        assert names == ["${OperatorsParameterName}", "/papyrus/monitoring/recipient-key", "${TriageParameterName}"]
    text = "".join(json.dumps(resources[r]) for r in OPERATOR_ROLES)
    assert "kms:" not in text and "secretsmanager" not in text and "dynamodb:Scan" not in text and "sqs:*" not in text


def test_each_role_touches_only_its_own_queue_table_and_logs(resources):
    core = {s["Sid"]: s for s in statements(resources["OperatorCoreRole"])}
    assert core["IngestQueue"]["Resource"] == {"Fn::GetAtt": ["OperatorIngestQueue", "Arn"]}
    assert core["EmailQueueSend"]["Action"] == "sqs:SendMessage"
    email = {s["Sid"]: s for s in statements(resources["OperatorEmailRole"])}
    assert email["EmailQueue"]["Resource"] == {"Fn::GetAtt": ["OperatorEmailQueue", "Arn"]}
    events = statements(resources["OperatorSesEventsRole"])
    assert {a for s in events for a in listify(s["Action"])} == {"cloudwatch:PutMetricData", "logs:CreateLogStream", "logs:PutLogEvents"}
    schedule = statements(resources["OperatorScheduleRole"])
    assert {a for s in schedule for a in listify(s["Action"])} == {"lambda:InvokeFunction", "sqs:SendMessage"}
    assert resources["OperatorScheduleRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"] == {"StringEquals": {"aws:SourceAccount": {"Ref": "AWS::AccountId"}}}


# --- schedules -------------------------------------------------------------------------------------------------------------------------

def test_flush_every_minute_and_reconcile_every_hour(resources):
    flush, reconcile = resources["OperatorFlushSchedule"]["Properties"], resources["OperatorReconcileSchedule"]["Properties"]
    assert flush["ScheduleExpression"] == "rate(1 minute)" and reconcile["ScheduleExpression"] == "rate(1 hour)"
    assert flush["Target"]["Arn"] == {"Fn::GetAtt": ["OperatorFlushFunction", "Arn"]}
    assert reconcile["Target"]["Arn"] == {"Fn::GetAtt": ["OperatorReconcileFunction", "Arn"]}
    for schedule in (flush, reconcile):
        assert schedule["FlexibleTimeWindow"] == {"Mode": "OFF"} and "DeadLetterConfig" in schedule["Target"]


def test_the_heartbeat_puts_a_valid_event_on_the_ingest_queue_every_fifteen_minutes(resources, whole):
    schedule = resources["OperatorHeartbeatSchedule"]["Properties"]
    assert schedule["ScheduleExpression"] == "rate(15 minutes)" and schedule["State"] == {"Ref": "OperatorHeartbeatState"}
    assert whole["Parameters"]["OperatorHeartbeatState"]["Default"] == "ENABLED"
    assert schedule["Target"]["Arn"] == {"Fn::GetAtt": ["OperatorIngestQueue", "Arn"]}
    envelope = json.loads(schedule["Target"]["Input"].replace("<aws.scheduler.scheduled-time>", "2026-11-04T12:00:00Z"))
    assert envelope["detail-type"] == "Notification Requested"
    detail = envelope["detail"]
    assert detail["kind"] == "caducus.heartbeat" and detail["schema"] == 1 and detail["eventId"] == "heartbeat-2026-11-04T12:00:00Z"
    assert schedule["Target"]["Input"].count("<aws.scheduler.scheduled-time>") == 2   # a different event id on every beat


# --- the two last-resort alerts --------------------------------------------------------------------------------------------------------

def alarm_actions(resources):
    return {r["Properties"]["AlarmName"]: r["Properties"] for r in resources.values()
            if r["Type"] in ("AWS::CloudWatch::Alarm", "AWS::CloudWatch::CompositeAlarm") and r["Properties"].get("AlarmActions")}


def test_the_old_alarms_still_email_by_sns_and_exactly_two_new_alerts_join_them(resources):
    notifying = alarm_actions(resources)
    assert set(notifying) == LEGACY_ALARMS | {"papyrus-operator-deadman", "papyrus-operator-ses-at-risk"}
    assert all(p["AlarmActions"] == [{"Ref": "AlarmTopic"}] for p in notifying.values())
    assert sorted(n for n in notifying if n.startswith(PREFIX)) == ["papyrus-operator-deadman", "papyrus-operator-ses-at-risk"]
    for name in ("papyrus-operator-deadman", "papyrus-operator-ses-at-risk"):
        assert notifying[name]["OKActions"] == [{"Ref": "AlarmTopic"}]   # both notify on ALARM and OK
    assert resources["AlarmEmailSubscription"]["Properties"]["TopicArn"] == {"Ref": "AlarmTopic"}   # the existing email keeps working


def test_the_dead_mans_switch_fires_after_three_missed_fifteen_minute_periods(resources):
    alarm = resources["OperatorDeadmanAlarm"]["Properties"]
    assert (alarm["Namespace"], alarm["MetricName"], alarm["Statistic"]) == ("Papyrus/Operator", "HeartbeatDelivered", "Sum")
    assert alarm["Period"] == 900 and alarm["EvaluationPeriods"] == alarm["DatapointsToAlarm"] == 3
    assert alarm["ComparisonOperator"] == "LessThanThreshold" and alarm["Threshold"] == 1
    assert alarm["TreatMissingData"] == "breaching"
    assert resources["OperatorHeartbeatSchedule"]["Properties"]["ScheduleExpression"] == "rate(15 minutes)"   # one beat per period
    for limit in ("account suspension", "mailbox"):
        assert limit in alarm["AlarmDescription"]   # says what it cannot see


def test_a_new_dead_mans_switch_does_not_fire_before_the_first_heartbeat_but_still_fires_if_none_ever_comes(resources):
    # 2026-11-05 16:45 UTC: the first create of the stack made papyrus-operator-deadman, which treats missing data as breaching, so it went to ALARM and
    # emailed on the spot, before any heartbeat could have run. The stack now writes one HeartbeatDelivered datapoint when it is created.
    alarm = resources["OperatorDeadmanAlarm"]
    assert alarm["Properties"]["TreatMissingData"] == "breaching"   # still a real dead-man: no data after the seed ages out means ALARM
    assert alarm["DependsOn"] == "OperatorDeadmanSeed"               # the seed is written before the alarm exists
    seed = resources["OperatorDeadmanSeed"]
    assert seed["Type"] == "Custom::DeadmanStart" and seed["Properties"]["ServiceToken"] == {"Fn::GetAtt": ["OperatorDeadmanSeedFunction", "Arn"]}
    code = resources["OperatorDeadmanSeedFunction"]["Properties"]["Code"]["ZipFile"]
    assert 'RequestType"] == "Create"' in code                       # on create only, never on an update or a delete
    assert 'MetricName": "HeartbeatDelivered"' in code and 'Namespace="Papyrus/Operator"' in code and '"Value": 1' in code
    assert "cfnresponse.SUCCESS" in code and "FAILED" not in code      # best effort: a failed write must not fail (and roll back) the deploy
    policy = resources["OperatorDeadmanSeedRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"][0]
    assert policy["Action"] == "cloudwatch:PutMetricData" and policy["Condition"]["StringEquals"]["cloudwatch:namespace"] == "Papyrus/Operator"
    # one datapoint of 1 is not below the threshold of 1, so the seeded period counts as a delivered beat, and it leaves the 3 x 15 minute window after 30 to 45 minutes
    assert alarm["Properties"]["Threshold"] == 1 and alarm["Properties"]["ComparisonOperator"] == "LessThanThreshold"


def test_ses_at_risk_is_one_alarm_over_the_recommended_lines_and_a_refused_send(resources):
    composite = resources["OperatorSesAtRiskAlarm"]["Properties"]
    assert composite["AlarmName"] == "papyrus-operator-ses-at-risk"
    rule = composite["AlarmRule"]["Fn::Sub"]
    children = {"OperatorSesBounceRateAlarm": ("AWS/SES", "Reputation.BounceRate", 0.05),
                "OperatorSesComplaintRateAlarm": ("AWS/SES", "Reputation.ComplaintRate", 0.001),
                "OperatorHeartbeatSendFailedAlarm": ("Papyrus/Operator", "HeartbeatSendFailed", 1)}
    for name, (namespace, metric, threshold) in children.items():
        props = resources[name]["Properties"]
        assert (props["Namespace"], props["MetricName"], props["Threshold"]) == (namespace, metric, threshold)
        assert props["ComparisonOperator"] == "GreaterThanOrEqualToThreshold" and props["TreatMissingData"] == "notBreaching"
        assert props["AlarmName"].startswith("papyrus-operator-ses-at-risk-")
        assert "AlarmActions" not in props and "OKActions" not in props   # one alert, from the composite
        assert "${%s}" % name in rule


def test_the_listener_ignores_exactly_the_prefix_the_last_resort_alarms_share(resources):
    named = {r["Properties"]["AlarmName"] for r in resources.values() if r["Type"] in ("AWS::CloudWatch::Alarm", "AWS::CloudWatch::CompositeAlarm")}
    operator = {n for n in named if n.startswith(PREFIX)}
    assert operator == {"papyrus-operator-deadman", "papyrus-operator-ses-at-risk", "papyrus-operator-ses-at-risk-bounce-rate",
                        "papyrus-operator-ses-at-risk-complaint-rate", "papyrus-operator-ses-at-risk-send-refused"}
    assert not [n for n in named - operator if n.startswith("papyrus-operator")]
    assert resources["OperatorAlarmRule"]["Properties"]["EventPattern"]["detail"]["alarmName"][0]["anything-but"]["prefix"] == PREFIX


# --- the test alarm --------------------------------------------------------------------------------------------------------------------

def test_the_test_alarm_has_no_actions_no_data_and_is_not_ignored_by_the_listener(resources):
    props = resources["OperatorTestAlarm"]["Properties"]
    assert props["AlarmName"] == TEST_ALARM and not TEST_ALARM.startswith(PREFIX)
    assert not {"AlarmActions", "OKActions", "InsufficientDataActions"} & set(props)
    assert props["TreatMissingData"] == "notBreaching"
    metric = (props["Namespace"], props["MetricName"])
    others = [(r["Properties"].get("Namespace"), r["Properties"].get("MetricName")) for n, r in resources.items()
              if r["Type"] == "AWS::CloudWatch::Alarm" and n != "OperatorTestAlarm"]
    assert metric not in others   # no other alarm reads the metric, and nothing publishes to it


def test_the_collector_and_router_resources_are_still_the_stacks_only_other_consumers_of_their_code_keys(resources):
    users = {n for n, r in resources.items() if r["Type"] == "AWS::Lambda::Function" and r["Properties"].get("Code", {}).get("S3Key") == {"Ref": "OperatorCodeKey"}}
    assert users == set(FUNCTIONS)


# --- the alarm catalog -----------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def catalog():
    return yaml.safe_load(CATALOG.read_text())


def first_match(catalog, name):
    for entry in catalog["alarms"]:
        found = re.match(entry["pattern"], name)
        if found:
            return entry, found.groupdict().get("site")
    return None, None


def test_every_entry_says_what_broke_the_impact_and_the_next_step(catalog):
    assert catalog["defaults"]["holdDownSeconds"] == 300
    for entry in catalog["alarms"]:
        re.compile(entry["pattern"])
        for field in ("product", "what", "impact", "next"):
            assert isinstance(entry[field], str) and entry[field].strip(), (entry["pattern"], field)
        assert entry["what"].rstrip().endswith(".") and entry["product"] in ("papyrus", "prospectus")


NINE = {
    "papyrus-monitoring-collector-errors": "Read the collector's log group.",
    "papyrus-monitoring-search-provider-failing": "renew the key or top up the plan",
    "papyrus-monitoring-router-errors": "latest ROUTERUN receipt",
    "papyrus-monitoring-router-dead-letters": "then redrive it",
    "papyrus-monitoring-decisions-stopped": "hand it to the Cyclotron session",
    "papyrus-newsletter-shipped-bounce-rate": "remove bad addresses",
    "papyrus-newsletter-shipped-complaint-rate": "check what was sent",
    "papyrus-scheduled-job-knowledge-run-shipped-JobFailureAlarm33B6C048-AbCdEf": "rerun the job",
    "papyrus-scheduled-job-knowledge-run-shipped-JobMissedWeekAlarmF3C1B7EE-AbCdEf": "start a run once the cause is fixed",
}


@pytest.mark.parametrize("name,words", sorted(NINE.items()))
def test_the_reviewed_wording_for_the_nine_patterns_is_kept(catalog, name, words):
    entry, _ = first_match(catalog, name)
    assert entry is not None and words in entry["next"]


def test_site_comes_from_the_alarm_name_where_the_name_has_one(catalog):
    assert first_match(catalog, "papyrus-newsletter-machines-on-machines-bounce-rate")[1] == "machines-on-machines"
    assert first_match(catalog, "papyrus-scheduled-job-knowledge-run-machines-on-machines-JobFailureAlarm33B6C048-x")[1] == "machines-on-machines"
    assert first_match(catalog, "papyrus-email-p-apyr-us-FailureAlarm-AbCd")[1] == "p-apyr-us"
    assert first_match(catalog, "papyrus-monitoring-router-errors")[1] is None


AMPLIFY = "amplify-dxxxxxxxxxxxxx-main-branch-0123456789-%s-AbC123-%s-xYz"


@pytest.mark.parametrize("construct,alarm,words", [
    ("reprojectondeploy3EEBD006", "DeployRenderDriftAlarmAFDD8E41", "--reconcile --dry-run"),
    ("s3projection7F93AA9D", "EdgeInvalidationPaths338340F0", "free 1,000 paths"),
    ("CliRemoteLogin54001B7F", "StartCeilingAlarmDAC2BB18", "login broker"),
    ("CliRemoteLogin54001B7F", "ThrottledAlarm5718E5A0", "reserved concurrency"),
])
def test_amplify_site_alarms_have_notes_from_what_the_alarms_mean(catalog, construct, alarm, words):
    entry, site = first_match(catalog, AMPLIFY % (construct, alarm))
    assert entry is not None and site == "dxxxxxxxxxxxxx"   # the app id is mapped to a site name in SSM, never in Git
    assert words in (entry["what"] + entry["next"])


def test_drift_notes_follow_the_reconcile_safety_rules(catalog):
    entry, _ = first_match(catalog, AMPLIFY % ("reprojectondeploy3EEBD006", "DeployRenderDriftAlarmAFDD8E41"))
    assert "Nothing was deleted" in entry["impact"] and "--allow-deletions" in entry["next"] and "dry-run" in entry["next"]


def test_prospectus_broker_alarms_are_labelled_prospectus_and_name_its_owner(catalog):
    for alarm in ("prospectus-cli-broker-StartCeilingAlarm-AbC", "prospectus-cli-broker-ThrottledAlarm-AbC"):
        entry, _ = first_match(catalog, alarm)
        assert entry["product"] == "prospectus" and "Prospectus session" in entry["next"]


def test_the_catalog_names_no_account_app_or_address(catalog):
    text = CATALOG.read_text()
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text) and not re.search(r"\b\d{12}\b", text)
    assert not re.search(r"\bd[0-9a-z]{12,13}\b", text)   # an Amplify app id


def test_the_test_alarm_has_notes_that_say_nothing_is_wrong(catalog):
    entry, _ = first_match(catalog, TEST_ALARM)
    assert "Nothing is wrong" in entry["what"] and entry["holdDownSeconds"] <= 60


def test_an_alarm_nobody_wrote_notes_for_matches_nothing(catalog):
    assert first_match(catalog, "some-new-team-alarm") == (None, None)
    assert not any(re.match(e["pattern"], "papyrus-operator-deadman") for e in catalog["alarms"])   # the listener never sees these


# --- the zip ---------------------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location("monitoring_build", MONITORING / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def wheel(tmp_path):
    path = tmp_path / "caducus-9.9.9-py3-none-any.whl"
    files = {"caducus/__init__.py": "", "caducus/cli.py": "import yaml", "caducus/storage.py": "import virtuus",
             "caducus/notify/__init__.py": "", "caducus/notify/handlers/router.py": "def handler(e, c=None): pass",
             "caducus/notify/data/notification-kinds.json": "{}", "caducus/notify/__pycache__/x.pyc": "x",
             "caducus-9.9.9.dist-info/METADATA": "Name: caducus"}
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return path


def test_the_pin_is_one_line_and_either_a_git_commit_or_a_pypi_version(build):
    line = build.caducus_requirement()
    assert re.fullmatch(r"caducus @ git\+https://github\.com/AnthusAI/Caducus\.git@[0-9a-f]{40}|caducus==\d+\.\d+\.\d+", line), line
    assert len([l for l in REQUIREMENT.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]) == 1


def test_a_pin_file_with_two_requirements_or_none_is_refused(build, tmp_path):
    for text in ("# nothing\n", "caducus==1.0.0\ncaducus==1.0.1\n", "requests==2\n"):
        path = tmp_path / "pin.txt"
        path.write_text(text)
        with pytest.raises(AssertionError):
            build.caducus_requirement(path)


def test_the_zip_holds_only_the_notify_package_and_the_catalog_as_json(build, wheel):
    entries = build.operator_entries(wheel)
    assert sorted(entries) == ["caducus/__init__.py", "caducus/notify/__init__.py", "caducus/notify/data/notification-kinds.json",
                               "caducus/notify/handlers/router.py", "config/alarm-catalog.json"]
    assert json.loads(entries["config/alarm-catalog.json"]) == yaml.safe_load(CATALOG.read_text())
    build.check_operator_entries(entries)


def test_a_zip_with_pyyaml_or_virtuus_is_refused(build, wheel):
    entries = build.operator_entries(wheel)
    for bad in ("yaml/__init__.py", "PyYAML-6.dist-info/METADATA", "virtuus/__init__.py"):
        with pytest.raises(AssertionError):
            build.check_operator_entries({**entries, bad: b""})


def test_the_build_is_deterministic_and_small(build, wheel, tmp_path):
    first = build.build_operator(tmp_path / "a.zip", wheel=wheel)
    second = build.build_operator(tmp_path / "b.zip", wheel=wheel)
    assert first == second and (tmp_path / "a.zip").read_bytes() == (tmp_path / "b.zip").read_bytes()
    with zipfile.ZipFile(tmp_path / "a.zip") as archive:
        assert {i.date_time for i in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        assert [i.filename for i in archive.infolist()] == sorted(i.filename for i in archive.infolist())
        assert not any(n.startswith(("yaml", "virtuus")) for n in archive.namelist())


def test_a_catalog_change_changes_the_zip_and_a_pin_change_changes_nothing_else(build, wheel, tmp_path):
    changed = tmp_path / "alarm-catalog.yaml"
    changed.write_text(CATALOG.read_text() + "  - pattern: '^x$'\n    product: papyrus\n    what: X.\n    impact: Y.\n    next: Z.\n")
    assert build.build_operator(tmp_path / "a.zip", wheel=wheel) != build.build_operator(tmp_path / "c.zip", wheel=wheel, catalog=changed)


def test_the_limits_leave_room_for_the_real_package(build):
    assert build.LAMBDA_UNZIPPED_LIMIT == 250 * 1024 * 1024 and build.LAMBDA_ZIPPED_LIMIT == 50 * 1024 * 1024


# --- the test command --------------------------------------------------------------------------------------------------------------------

class FakeCloudWatch:
    def __init__(self):
        self.calls = []

    def set_alarm_state(self, **kwargs):
        self.calls.append(kwargs)

    def describe_alarms(self, AlarmNames):
        import datetime

        return {"MetricAlarms": [{"AlarmName": AlarmNames[0], "StateValue": "OK", "StateUpdatedTimestamp": datetime.datetime(2026, 11, 4, tzinfo=datetime.timezone.utc)}]}


class FakeSts:
    def __init__(self, account):
        self.account = account

    def get_caller_identity(self):
        return {"Account": self.account}


@pytest.fixture(scope="module")
def tester():
    spec = importlib.util.spec_from_file_location("operator_test_alarm", MONITORING / "operator_test_alarm.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_test_command_changes_only_the_test_alarm_and_only_in_the_right_account(tester, build):
    assert tester.ALARM == TEST_ALARM and tester.ACCOUNT == build.ACCOUNT
    cloudwatch, lines = FakeCloudWatch(), []
    assert tester.run("raise", cloudwatch, FakeSts(tester.ACCOUNT), out=lines.append) == 0
    assert tester.run("clear", cloudwatch, FakeSts(tester.ACCOUNT), out=lines.append) == 0
    assert [(c["AlarmName"], c["StateValue"]) for c in cloudwatch.calls] == [(TEST_ALARM, "ALARM"), (TEST_ALARM, "OK")]
    assert all("Nothing is wrong" in c["StateReason"] for c in cloudwatch.calls)
    other = FakeCloudWatch()
    assert tester.run("raise", other, FakeSts("not-production"), out=lines.append) == 2 and other.calls == []


def test_the_test_command_dry_run_and_status_write_nothing(tester):
    cloudwatch, lines = FakeCloudWatch(), []
    assert tester.run("raise", cloudwatch, FakeSts(tester.ACCOUNT), dry_run=True, out=lines.append) == 0
    assert tester.run("status", cloudwatch, FakeSts(tester.ACCOUNT), out=lines.append) == 0
    assert cloudwatch.calls == [] and lines[0] == f"Would set {TEST_ALARM} to ALARM." and lines[1].startswith(TEST_ALARM + ": OK")


def test_the_test_command_takes_no_alarm_name(tester):
    with pytest.raises(SystemExit):
        tester.main(["raise", "--alarm", "papyrus-monitoring-router-errors"])


# --- the real package, when it can be imported -------------------------------------------------------------------------------------------

caducus = pytest.importorskip("caducus.notify.fakes", reason="caducus is not importable; set PYTHONPATH to a Caducus checkout")


@pytest.fixture()
def world(tmp_path):
    from caducus.notify.catalog import catalog_from_mapping

    world = caducus.World(operators=1)
    world.catalog = catalog_from_mapping(yaml.safe_load(CATALOG.read_text()))
    world.router._catalog = world.catalog
    return world


def delivered(world):
    world.send_all_queued()
    return world.mailer.calls


def test_a_catalogued_alarm_arrives_with_what_broke_the_impact_and_the_next_step(world):
    world.alarm("papyrus-monitoring-router-dead-letters")
    (mail,) = delivered(world)
    assert mail["subject"].startswith("[ALARM] papyrus:") and "No triage notes" not in mail["text"]
    for label in ("What broke:", "Impact:", "Next step:", "Open the alarm:"):
        assert label in mail["text"]
    assert "redrive" in mail["text"]


def test_an_amplify_alarm_with_a_site_map_names_the_site_and_an_unknown_alarm_still_sends(world):
    from caducus.notify.triage import TriageSettings

    world.router._triage = TriageSettings(sites={"dxxxxxxxxxxxxx": "shipped"}, role_name="AdministratorAccess")
    world.alarm(AMPLIFY % ("s3projection7F93AA9D", "EdgeInvalidationPaths338340F0"))
    world.alarm("some-new-team-alarm")
    first, second = delivered(world)
    assert "papyrus/shipped" in first["subject"] and "Where: papyrus/shipped" in first["text"]
    assert "No triage notes yet" in second["text"]
    # no portal URL is set, so the link is the plain console and still works
    assert "https://us-east-1.console.aws.amazon.com/cloudwatch/home" in second["text"]


def test_the_test_alarm_sends_once_and_clears_with_one_message(world):
    world.alarm(TEST_ALARM)
    world.alarm(TEST_ALARM, state="OK")
    world.tick(61)   # the 60 second hold-down of the test alarm's entry
    mails = delivered(world)
    assert [m["subject"].split("]")[0] for m in mails] == ["[ALARM", "[CLEARED"]
    assert "Nothing is wrong" in mails[0]["text"]
