"""Static checks of the per-site SES sending stack (PPY-874ad4)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

TEMPLATE = Path(__file__).resolve().parents[3] / "infra" / "newsletter" / "papyrus-newsletter-sending.yaml"


class _Loader(yaml.SafeLoader):
    pass


def _tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    if suffix == "GetAtt" and isinstance(value, str):
        value = value.split(".", 1)
    return {suffix if suffix in ("Ref", "Condition") else f"Fn::{suffix}": value}


_Loader.add_multi_constructor("!", _tag)


@pytest.fixture(scope="module")
def template():
    return yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=_Loader)


@pytest.fixture(scope="module")
def resources(template):
    return template["Resources"]


def _of_type(resources, type_name):
    return {k: v for k, v in resources.items() if v["Type"] == type_name}


def test_parameters(template):
    params = template["Parameters"]
    assert set(params) == {
        "SiteId", "SendingDomain", "HostedZoneId", "MailFromSubdomain", "DmarcPolicy", "CreateDmarcRecord",
    }
    assert params["MailFromSubdomain"]["Default"] == "bounce"
    assert params["DmarcPolicy"]["AllowedValues"] == ["none", "quarantine", "reject"]
    assert params["DmarcPolicy"]["Default"] == "quarantine"
    assert params["CreateDmarcRecord"]["Default"] == "true"


def test_identity(resources):
    identity = resources["EmailIdentity"]["Properties"]
    assert identity["DkimSigningAttributes"]["NextSigningKeyLength"] == "RSA_2048_BIT"
    assert identity["MailFromAttributes"]["BehaviorOnMxFailure"] == "USE_DEFAULT_VALUE"
    assert identity["ConfigurationSetAttributes"]["ConfigurationSetName"] == {"Ref": "ConfigurationSet"}


def test_route53_records(resources):
    records = _of_type(resources, "AWS::Route53::RecordSet")
    assert set(records) == {
        "DkimRecord1", "DkimRecord2", "DkimRecord3", "MailFromMxRecord", "MailFromSpfRecord", "DmarcRecord",
    }
    for n in (1, 2, 3):
        props = records[f"DkimRecord{n}"]["Properties"]
        assert props["Type"] == "CNAME"
        assert props["Name"] == {"Fn::GetAtt": ["EmailIdentity", f"DkimDNSTokenName{n}"]}
        assert props["ResourceRecords"] == [{"Fn::GetAtt": ["EmailIdentity", f"DkimDNSTokenValue{n}"]}]
        assert props["TTL"] == "1800"
    assert records["MailFromMxRecord"]["Properties"]["Type"] == "MX"
    assert records["MailFromMxRecord"]["Properties"]["Name"] == {"Fn::Sub": "${MailFromSubdomain}.${SendingDomain}"}
    assert "feedback-smtp" in records["MailFromMxRecord"]["Properties"]["ResourceRecords"][0]["Fn::Sub"]
    assert records["MailFromSpfRecord"]["Properties"]["Type"] == "TXT"
    assert "v=spf1 include:amazonses.com" in records["MailFromSpfRecord"]["Properties"]["ResourceRecords"][0]
    dmarc = records["DmarcRecord"]
    assert dmarc["Condition"] == "CreateDmarc"
    assert dmarc["Properties"]["Name"] == {"Fn::Sub": "_dmarc.${SendingDomain}"}
    text = dmarc["Properties"]["ResourceRecords"][0]["Fn::Sub"]
    assert "v=DMARC1; p=${DmarcPolicy}; adkim=r; aspf=r" in text
    assert "rua" not in text


def test_configuration_set(resources):
    props = resources["ConfigurationSet"]["Properties"]
    assert props["Name"] == {"Fn::Sub": "papyrus-${SiteId}"}
    assert props["ReputationOptions"]["ReputationMetricsEnabled"] is True
    assert props["SendingOptions"]["SendingEnabled"] is True
    assert props["SuppressionOptions"]["SuppressedReasons"] == ["BOUNCE", "COMPLAINT"]
    assert "TrackingOptions" not in props


def test_topic_and_policy(resources):
    assert resources["EventTopic"]["Properties"]["TopicName"] == {"Fn::Sub": "papyrus-newsletter-events-${SiteId}"}
    statement = resources["EventTopicPolicy"]["Properties"]["PolicyDocument"]["Statement"][0]
    assert statement["Principal"] == {"Service": "ses.amazonaws.com"}
    assert statement["Action"] == "sns:Publish"
    assert statement["Condition"]["StringEquals"]["aws:SourceAccount"] == {"Ref": "AWS::AccountId"}


def test_event_destinations(resources):
    destinations = _of_type(resources, "AWS::SES::ConfigurationSetEventDestination")
    assert set(destinations) == {"SnsEventDestination", "CloudWatchEventDestination"}
    sns = destinations["SnsEventDestination"]["Properties"]["EventDestination"]
    assert set(sns["MatchingEventTypes"]) == {
        "SEND", "DELIVERY", "BOUNCE", "COMPLAINT", "REJECT", "RENDERING_FAILURE", "DELIVERY_DELAY",
    }
    assert sns["SnsDestination"]["TopicARN"] == {"Ref": "EventTopic"}
    cw = destinations["CloudWatchEventDestination"]["Properties"]["EventDestination"]
    assert set(cw["MatchingEventTypes"]) == {"SEND", "BOUNCE", "COMPLAINT"}
    dims = cw["CloudWatchDestination"]["DimensionConfigurations"]
    assert len(dims) == 1
    assert dims[0]["DimensionName"] == "ses:configuration-set"
    assert dims[0]["DimensionValueSource"] == "MESSAGE_TAG"
    assert dims[0]["DefaultDimensionValue"] == {"Fn::Sub": "papyrus-${SiteId}"}


def test_outputs(template):
    assert set(template["Outputs"]) == {"IdentityName", "ConfigurationSetName", "EventTopicArn"}


def test_no_tracking_rua_or_addresses():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "Tracking" not in text
    assert "rua=" not in text
    assert "mailto:" not in text
    assert "@" not in text
