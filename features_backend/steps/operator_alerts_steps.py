"""Steps for operator-alerts.feature: the CloudFormation templates and the catalog are read as data; the email scenarios run the caducus
package on its in-memory fakes when it is importable, and skip otherwise (set PYTHONPATH to a Caducus checkout)."""
from pathlib import Path
import importlib.util
import json
import re
import tempfile
import zipfile

from behave import given, then, when
import yaml

ROOT = Path(__file__).resolve().parents[2]
MONITORING = ROOT / "infra" / "monitoring"
TEMPLATE = MONITORING / "papyrus-monitoring.yaml"
SENDING = ROOT / "infra" / "newsletter" / "papyrus-newsletter-sending.yaml"
CATALOG = MONITORING / "alarm-catalog.yaml"
PREFIX = "papyrus-operator-"
TEST_ALARM = "papyrus-notify-test-alarm"


class Loader(yaml.SafeLoader):
    pass


def _tag(loader, suffix, node):
    value = (loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else
             loader.construct_sequence(node, deep=True) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node, deep=True))
    if suffix == "GetAtt" and isinstance(value, str):
        value = value.split(".", 1)
    return {suffix if suffix in ("Ref", "Condition") else f"Fn::{suffix}": value}


Loader.add_multi_constructor("!", _tag)


def listify(value):
    return value if isinstance(value, list) else [value]


def statements(role):
    return [s for p in role["Properties"]["Policies"] for s in p["PolicyDocument"]["Statement"]]


def alarm_props(resources):
    return {r["Properties"]["AlarmName"]: r["Properties"] for r in resources.values()
            if r["Type"] in ("AWS::CloudWatch::Alarm", "AWS::CloudWatch::CompositeAlarm")}


def first_match(catalog, name):
    return next((e for e in catalog["alarms"] if re.match(e["pattern"], name)), None)


# --- the monitoring template ---------------------------------------------------------------------------------------------------------

@given("the operator listener template")
def step_template(context):
    context.template = yaml.load(TEMPLATE.read_text(), Loader=Loader)
    context.resources = context.template["Resources"]


@then("a rule on the default bus takes every CloudWatch alarm state change")
def step_rule(context):
    rule = context.resources["OperatorAlarmRule"]["Properties"]
    assert "EventBusName" not in rule
    assert rule["EventPattern"]["source"] == ["aws.cloudwatch"] and rule["EventPattern"]["detail-type"] == ["CloudWatch Alarm State Change"]


@then('that rule skips alarms named "{prefix}" and sends the rest to the ingest queue')
def step_skips(context, prefix):
    rule = context.resources["OperatorAlarmRule"]["Properties"]
    assert rule["EventPattern"]["detail"]["alarmName"] == [{"anything-but": {"prefix": prefix}}]
    assert rule["Targets"][0]["Arn"] == {"Fn::GetAtt": ["OperatorIngestQueue", "Arn"]}


@then("the reconcile function skips the same prefix")
def step_reconcile_prefix(context):
    env = context.resources["OperatorReconcileFunction"]["Properties"]["Environment"]["Variables"]
    assert env["IGNORE_ALARM_PREFIXES"] == PREFIX


@then("the ingest queue and the email queue each redrive to their own dead-letter queue")
def step_redrive(context):
    for queue, dead in (("OperatorIngestQueue", "OperatorIngestDeadLetterQueue"), ("OperatorEmailQueue", "OperatorEmailDeadLetterQueue")):
        assert context.resources[queue]["Properties"]["RedrivePolicy"]["deadLetterTargetArn"] == {"Fn::GetAtt": [dead, "Arn"]}


@then("both dead-letter queues keep messages for fourteen days")
def step_retention(context):
    for dead in ("OperatorIngestDeadLetterQueue", "OperatorEmailDeadLetterQueue"):
        assert context.resources[dead]["Properties"]["MessageRetentionPeriod"] == 14 * 86400


@then("the email function may send only as the alerts mailbox of the operator domain, with the operator configuration set")
def step_send_pinned(context):
    (send,) = [s for s in statements(context.resources["OperatorEmailRole"]) if s["Action"] == "ses:SendEmail"]
    assert send["Condition"] == {"StringEquals": {"ses:FromAddress": {"Fn::Sub": "alerts@${OperatorSendingDomain}"}}}
    assert [r["Fn::Sub"].rsplit(":", 1)[1] for r in send["Resource"]] == ["identity/${OperatorSendingDomain}", "configuration-set/${OperatorConfigurationSet}"]


@then("the operator listener template contains no email address")
def step_no_address(context):
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", TEMPLATE.read_text())


@then("the operators are read from the SSM parameter that the alarm topic's subscription already uses")
def step_operators(context):
    assert context.template["Parameters"]["OperatorsParameterName"]["Default"] == "/papyrus/shipped/knowledge-run/alarm-email"
    assert context.template["Parameters"]["AlarmEmailParameter"]["Default"] == "/papyrus/shipped/knowledge-run/alarm-email"


@then("only three grants name no resource, and each is one that AWS cannot scope")
def step_wildcards(context):
    found = set()
    for role in ("OperatorCoreRole", "OperatorEmailRole", "OperatorSesEventsRole", "OperatorScheduleRole", "OperatorRecipientKeyRole"):
        for statement in statements(context.resources[role]):
            assert not any("*" in a for a in listify(statement["Action"]))
            if "*" in listify(statement["Resource"]):
                found |= set(listify(statement["Action"]))
    assert found == {"cloudwatch:DescribeAlarms", "ses:GetAccount", "cloudwatch:PutMetricData"}


@then("the listener's roles read exactly three parameters and decrypt with no key grant")
def step_params(context):
    for role in ("OperatorCoreRole", "OperatorEmailRole"):
        (read,) = [s for s in statements(context.resources[role]) if s["Action"] == "ssm:GetParameter"]
        assert len(read["Resource"]) == 3
        assert "kms:" not in json.dumps(context.resources[role])


@then("the five existing monitoring alarms still notify the alarm topic")
def step_legacy(context):
    legacy = {n: p for n, p in alarm_props(context.resources).items() if n.startswith("papyrus-monitoring-") and n not in ("papyrus-monitoring-suggest-dead-letters", "papyrus-monitoring-story-dead-letters")}   # the suggestion and story dead-letter alarms are newer than the parallel run
    assert len(legacy) == 5 and all(p["AlarmActions"] == [{"Ref": "AlarmTopic"}] for p in legacy.values())


@then("the topic still has its email subscription")
def step_subscription(context):
    subscription = context.resources["AlarmEmailSubscription"]["Properties"]
    assert subscription["Protocol"] == "email" and subscription["Endpoint"] == {"Ref": "AlarmEmailParameter"}


@then("no existing resource of the stack is changed by the operator listener")
def step_unchanged(context):
    # the collector and the router keep their own code keys; only operator functions use the operator zip
    uses = {n for n, r in context.resources.items() if r["Type"] == "AWS::Lambda::Function" and r["Properties"].get("Code", {}).get("S3Key") == {"Ref": "OperatorCodeKey"}}
    assert uses and all(n.startswith("Operator") for n in uses)
    assert context.resources["CollectorFunction"]["Properties"]["Code"]["S3Key"] == {"Ref": "CodeKey"}
    assert context.resources["RouterFunction"]["Properties"]["Code"]["S3Key"] == {"Ref": "RouterCodeKey"}


@then('exactly two alarms named "{prefix}" notify the alarm topic, on ALARM and on OK')
def step_two(context, prefix):
    notifying = {n: p for n, p in alarm_props(context.resources).items() if n.startswith(prefix) and p.get("AlarmActions")}
    assert sorted(notifying) == ["papyrus-operator-deadman", "papyrus-operator-ses-at-risk"]
    assert all(p["AlarmActions"] == p["OKActions"] == [{"Ref": "AlarmTopic"}] for p in notifying.values())


@then("the dead-man alarm breaches when fewer than one heartbeat is delivered in each of three fifteen minute periods")
def step_deadman(context):
    alarm = context.resources["OperatorDeadmanAlarm"]["Properties"]
    assert alarm["MetricName"] == "HeartbeatDelivered" and alarm["Period"] == 900
    assert alarm["EvaluationPeriods"] == alarm["DatapointsToAlarm"] == 3 and alarm["Threshold"] == 1
    assert alarm["ComparisonOperator"] == "LessThanThreshold" and alarm["TreatMissingData"] == "breaching"


@then("the SES alert is one composite alarm over the bounce rate, the complaint rate and a refused heartbeat send")
def step_ses(context):
    rule = context.resources["OperatorSesAtRiskAlarm"]["Properties"]["AlarmRule"]["Fn::Sub"]
    for child in ("OperatorSesBounceRateAlarm", "OperatorSesComplaintRateAlarm", "OperatorHeartbeatSendFailedAlarm"):
        assert "${%s}" % child in rule and "AlarmActions" not in context.resources[child]["Properties"]
    assert context.resources["OperatorSesBounceRateAlarm"]["Properties"]["Threshold"] == 0.05
    assert context.resources["OperatorSesComplaintRateAlarm"]["Properties"]["Threshold"] == 0.001


@then("a schedule puts a heartbeat event on the ingest queue every fifteen minutes with a different event id each time")
def step_heartbeat(context):
    schedule = context.resources["OperatorHeartbeatSchedule"]["Properties"]
    assert schedule["ScheduleExpression"] == "rate(15 minutes)"
    assert schedule["Target"]["Arn"] == {"Fn::GetAtt": ["OperatorIngestQueue", "Arn"]}
    first = json.loads(schedule["Target"]["Input"].replace("<aws.scheduler.scheduled-time>", "2026-11-04T12:00:00Z"))["detail"]
    second = json.loads(schedule["Target"]["Input"].replace("<aws.scheduler.scheduled-time>", "2026-11-04T12:15:00Z"))["detail"]
    assert first["kind"] == "caducus.heartbeat" and first["eventId"] != second["eventId"]


@then("a rule sends SES events of the operator configuration set to a function that counts the delivered heartbeat")
def step_ses_events(context):
    rule = context.resources["OperatorSesEventsRule"]["Properties"]
    assert rule["EventPattern"]["detail"]["mail"]["tags"]["ses:configuration-set"] == [{"Ref": "OperatorConfigurationSet"}]
    assert context.resources["OperatorSesEventsFunction"]["Properties"]["Handler"] == "caducus.notify.handlers.ses_events.handler"


# --- the catalog and the email -------------------------------------------------------------------------------------------------------

@given("Papyrus's alarm catalog and the caducus package")
def step_catalog(context):
    if importlib.util.find_spec("caducus") is None:
        context.scenario.skip("caducus is not importable; set PYTHONPATH to a Caducus checkout")
        return
    from caducus.notify.catalog import catalog_from_mapping
    from caducus.notify.fakes import World

    context.data = yaml.safe_load(CATALOG.read_text())
    context.world = World(operators=1)
    context.world.catalog = catalog_from_mapping(context.data)
    context.world.router._catalog = context.world.catalog


@when('the alarm "{name}" fires')
def step_fires(context, name):
    context.world.alarm(name)
    context.world.send_all_queued()
    context.mails = context.world.mailer.calls


@then("one email is sent with what broke, the impact, the next step and a link")
def step_one_email(context):
    (mail,) = context.mails
    for label in ("What broke:", "Impact:", "Next step:", "Open the alarm:"):
        assert label in mail["text"], label


@then("the next step says to redrive the dead-letter queue")
def step_redrive_text(context):
    assert "redrive" in context.mails[0]["text"]


@then('one email is sent that says "{words}"')
def step_no_notes(context, words):
    (mail,) = context.mails
    assert words in mail["text"]


@then("the deploy render drift alarm tells the operator to reconcile with a dry run first and that nothing was deleted")
def step_drift(context):
    entry = first_match(context.data, "amplify-dxxxxxxxxxxxxx-main-branch-0123456789-reprojectondeploy3EEBD006-A-DeployRenderDriftAlarmAFDD8E41-b")
    assert "--reconcile --dry-run" in entry["next"] and "Nothing was deleted" in entry["impact"]


@then("the invalidation paths alarm says it is about the free monthly allowance and that readers are not affected")
def step_invalidation(context):
    entry = first_match(context.data, "amplify-dxxxxxxxxxxxxx-main-branch-0123456789-s3projection7F93AA9D-A-EdgeInvalidationPaths338340F0-b")
    assert "free 1,000 paths a month" in entry["what"] and "readers are not affected" in entry["impact"]


@then("no app id, account id or address is in the catalog")
def step_catalog_clean(context):
    text = CATALOG.read_text()
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text) and not re.search(r"\b\d{12}\b", text) and not re.search(r"\bd[0-9a-z]{12,13}\b", text)


@when("the test alarm is set to ALARM and then to OK")
def step_test_alarm(context):
    context.world.alarm(TEST_ALARM)
    context.world.alarm(TEST_ALARM, state="OK")
    context.world.tick(61)
    context.world.send_all_queued()
    context.mails = context.world.mailer.calls


@then("exactly two emails are sent, one for the alarm and one for clearing it")
def step_two_emails(context):
    assert [m["subject"].split("]")[0] for m in context.mails] == ["[ALARM", "[CLEARED"]


@then("the test alarm has no alarm actions, so neither the SNS email nor any other system hears it")
def step_test_no_actions(context):
    resources = yaml.load(TEMPLATE.read_text(), Loader=Loader)["Resources"]
    assert not {"AlarmActions", "OKActions", "InsufficientDataActions"} & set(resources["OperatorTestAlarm"]["Properties"])


# --- the operator sending identity ---------------------------------------------------------------------------------------------------

@given("the newsletter sending stack template")
def step_sending(context):
    context.sending = yaml.load(SENDING.read_text(), Loader=Loader)


@then("it sends delivery events to the default event bus when asked, and keeps the SNS topic by default")
def step_transport(context):
    template = context.sending
    assert template["Parameters"]["EventTransport"]["Default"] == "sns"
    assert template["Resources"]["EventBridgeEventDestination"]["Condition"] == "UseEventBridge"
    assert template["Resources"]["EventBridgeEventDestination"]["Properties"]["EventDestination"]["EventBridgeDestination"]["EventBusArn"]["Fn::Sub"].endswith("event-bus/default")
    assert all(template["Resources"][n]["Condition"] == "UseSns" for n in ("EventTopic", "EventTopicPolicy", "SnsEventDestination"))


@then("no event destination of the stack includes opens or clicks")
def step_no_tracking(context):
    for resource in context.sending["Resources"].values():
        if resource["Type"] == "AWS::SES::ConfigurationSetEventDestination":
            assert not {"OPEN", "CLICK"} & set(resource["Properties"]["EventDestination"]["MatchingEventTypes"])


# --- the zip -------------------------------------------------------------------------------------------------------------------------

@given("the operator zip build")
def step_build(context):
    spec = importlib.util.spec_from_file_location("monitoring_build", MONITORING / "build.py")
    context.build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(context.build)
    context.scratch = Path(tempfile.mkdtemp())
    context.wheel = context.scratch / "caducus-0-py3-none-any.whl"
    with zipfile.ZipFile(context.wheel, "w") as archive:
        archive.writestr("caducus/__init__.py", "")
        archive.writestr("caducus/cli.py", "import yaml")
        archive.writestr("caducus/notify/handlers/router.py", "def handler(event, context=None): pass")


@then("the pin is a single line that is easy to change to a PyPI version")
def step_pin(context):
    line = context.build.caducus_requirement()
    assert re.fullmatch(r"caducus @ git\+https://github\.com/AnthusAI/Caducus\.git@[0-9a-f]{40}|caducus==[0-9.]+", line)


@then("building twice from the same pin and catalog gives the same bytes")
def step_deterministic(context):
    assert context.build.build_operator(context.scratch / "a.zip", wheel=context.wheel) == context.build.build_operator(context.scratch / "b.zip", wheel=context.wheel)
    assert (context.scratch / "a.zip").read_bytes() == (context.scratch / "b.zip").read_bytes()


@then("the zip holds no PyYAML and is far inside Lambda's size limits")
def step_size(context):
    with zipfile.ZipFile(context.scratch / "a.zip") as archive:
        assert not any(n.startswith(("yaml", "PyYAML", "virtuus")) for n in archive.namelist())
        assert sum(i.file_size for i in archive.infolist()) < context.build.LAMBDA_UNZIPPED_LIMIT // 100
