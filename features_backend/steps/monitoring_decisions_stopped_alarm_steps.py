"""Steps for monitoring-decisions-stopped-alarm.feature: the CloudFormation template is read as data, and the alarm's rule is applied
to hourly totals by the same periods and datapoints the template declares (the expression itself is checked as text)."""
from pathlib import Path
import re

from behave import given, then, when
import yaml

TEMPLATE = Path(__file__).resolve().parents[2] / "infra/monitoring/papyrus-monitoring.yaml"
EXPRESSION = "IF(decided == 0 AND awaiting > 0, 1, 0)"


def load_template():
    class Loader(yaml.SafeLoader):
        pass
    Loader.add_multi_constructor("!", lambda loader, suffix, node: None)
    return yaml.load(TEMPLATE.read_text(), Loader)["Resources"]


def alarm_of(context):
    return context.resources["DecisionsStoppedAlarm"]["Properties"]


def filter_for(context, metric_name):
    found = [r["Properties"] for r in context.resources.values()
             if r["Type"] == "AWS::Logs::MetricFilter" and r["Properties"]["MetricTransformations"][0]["MetricName"] == metric_name]
    assert len(found) == 1, found
    return found[0]


@given("the monitoring stack template for the decisions-stopped alarm")
def step_template(context):
    context.resources = load_template()


@then("every alarm in the stack notifies the one alarm topic")
def step_notifies(context):
    # The operator listener's own alarms (papyrus-operator-*, features_backend/operator-alerts.feature) and its test alarm
    # sit beside these six (the suggestion dead-letter alarm is the sixth, the story dead-letter alarm the seventh); the seven monitoring alarms still each notify the one topic.
    alarms = [r["Properties"] for r in context.resources.values() if r["Type"] == "AWS::CloudWatch::Alarm"
              and not r["Properties"]["AlarmName"].startswith(("papyrus-operator-", "papyrus-notify-test-"))]
    assert len(alarms) == 7 and all(len(a["AlarmActions"]) == 1 for a in alarms)
    every = [r["Properties"] for r in context.resources.values() if r["Type"] in ("AWS::CloudWatch::Alarm", "AWS::CloudWatch::CompositeAlarm")]
    uses = sum(len(a.get("AlarmActions", [])) + len(a.get("OKActions", [])) for a in every)
    assert TEMPLATE.read_text().count("- !Ref AlarmTopic") == uses
    assert context.resources["AlarmTopic"]["Type"] == "AWS::SNS::Topic"


@then("that topic has one subscription, by email, to an address read from an SSM parameter")
def step_subscription(context):
    subscriptions = [r for r in context.resources.values() if r["Type"] == "AWS::SNS::Subscription"]
    assert len(subscriptions) == 1 and subscriptions[0]["Properties"]["Protocol"] == "email"
    text = TEMPLATE.read_text()
    assert "Endpoint: !Ref AlarmEmailParameter" in text
    assert "AlarmEmailParameter:\n    Type: AWS::SSM::Parameter::Value<String>" in text


@then("the template contains no email address")
def step_no_address(context):
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", TEMPLATE.read_text())


@then('a metric filter on the router log group makes "{metric}" from "{field}" in the "{namespace}" namespace')
def step_filter(context, metric, field, namespace):
    props = filter_for(context, metric)
    transformation = props["MetricTransformations"][0]
    assert transformation["MetricNamespace"] == namespace and transformation["MetricValue"] == "$." + field
    assert props["FilterPattern"] == "{ $." + field + " >= 0 }"   # lines with the number, zero included: a zero is a real datapoint
    assert "DefaultValue" not in transformation   # no line, no datapoint: absence stays missing data


@then('"{name}" alarms when decided is 0 and awaiting is above 0, for 2 of 2 hourly periods')
def step_alarm(context, name):
    props = alarm_of(context)
    assert props["AlarmName"] == name
    by_id = {m["Id"]: m for m in props["Metrics"]}
    assert by_id["stopped"]["Expression"] == EXPRESSION and by_id["stopped"]["ReturnData"] is True
    assert by_id["decided"]["MetricStat"]["Metric"]["MetricName"] == "RouterDecided" and by_id["decided"]["MetricStat"]["Stat"] == "Sum"
    assert by_id["awaiting"]["MetricStat"]["Metric"]["MetricName"] == "RouterAwaiting" and by_id["awaiting"]["MetricStat"]["Stat"] == "Maximum"
    assert by_id["decided"]["MetricStat"]["Period"] == by_id["awaiting"]["MetricStat"]["Period"] == 3600
    assert props["EvaluationPeriods"] == props["DatapointsToAlarm"] == 2
    assert props["Threshold"] == 1 and props["ComparisonOperator"] == "GreaterThanOrEqualToThreshold"


@then("missing data does not breach the alarm")
def step_missing(context):
    assert alarm_of(context)["TreatMissingData"] == "notBreaching"


# Hourly (decided sum, awaiting max) as read from the router log; None is an hour with no log line at all.
QUIET_NIGHT = [(0, 0)] * 8
NOV_2 = [(43, 0), (0, 10), (9, 97), (110, 96)]
NOV_3 = [(100, 65), (124, 77), (34, 197), (0, 338), (0, 413), (0, 505), (0, 585), (66, 0)]
NOV_3_HOURS = [14, 15, 16, 17, 18, 19, 20, 27]   # the last is 03:00 on 2026-11-04, when decisions returned


def breaching(hour):
    if hour is None:
        return False   # TreatMissingData: notBreaching
    decided, awaiting = hour
    return decided == 0 and awaiting > 0


def evaluate(hours):
    props = alarm_of_template()
    window = props["EvaluationPeriods"]
    return [index for index in range(len(hours)) if index + 1 >= window and all(breaching(h) for h in hours[index + 1 - window:index + 1])]


def alarm_of_template():
    return load_template()["DecisionsStoppedAlarm"]["Properties"]


@given("the hourly router totals of a quiet night")
def step_quiet(context):
    context.hours = QUIET_NIGHT


@given("the hourly router totals of 2026-11-02, when one hour had ten jobs waiting and no decisions")
def step_nov2(context):
    context.hours = NOV_2


@given("the hourly router totals of 2026-11-03, when the last decision was recorded at 16:28 UTC")
def step_nov3(context):
    context.hours = NOV_3


@given("two hours in which the router logged nothing")
def step_nothing(context):
    context.hours = [None, None, None]


@when("the alarm is evaluated over those hours")
def step_evaluate(context):
    context.fired = evaluate(context.hours)


@then("it never fires")
def step_never(context):
    assert context.fired == [], context.fired


@then("it first fires in the 18:00 UTC hour, about two hours after the last decision")
def step_first(context):
    assert NOV_3_HOURS[context.fired[0]] == 18, context.fired


@then("it keeps firing until decisions return")
def step_keeps(context):
    assert [NOV_3_HOURS[i] for i in context.fired] == [18, 19, 20], context.fired
