import unittest
from pathlib import Path

import yaml

TEMPLATE_DIRECTORY = Path(__file__).resolve().parents[3] / "infra" / "edge"
CLOUDFRONT_ALIAS_HOSTED_ZONE = "Z2FDTNDATAQYW2"


class _TemplateLoader(yaml.SafeLoader):
    pass


def _intrinsic(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {"Fn::" + tag_suffix if tag_suffix not in ("Ref", "Condition") else tag_suffix: value}


_TemplateLoader.add_multi_constructor("!", _intrinsic)


def load_template(file_name):
    return yaml.load((TEMPLATE_DIRECTORY / file_name).read_text(), Loader=_TemplateLoader)


class ConsoleEdgeTemplateTests(unittest.TestCase):
    """The console host has its own CloudFront distribution and certificate; it never touches the public edge."""

    def setUp(self):
        self.template = load_template("shipped-console.yaml")
        self.resources = self.template["Resources"]
        self.distribution = self.resources["ConsoleDistribution"]["Properties"]["DistributionConfig"]

    def test_the_stack_owns_a_dns_validated_certificate_for_the_console_host(self):
        certificate = self.resources["ConsoleCertificate"]
        self.assertEqual(certificate["Type"], "AWS::CertificateManager::Certificate")
        self.assertEqual(certificate["Properties"]["ValidationMethod"], "DNS")
        self.assertEqual(certificate["Properties"]["DomainName"], {"Ref": "ConsoleHost"})
        self.assertEqual(certificate["Properties"]["DomainValidationOptions"][0]["HostedZoneId"], {"Ref": "HostedZoneId"})
        self.assertEqual(self.distribution["Aliases"], [{"Ref": "ConsoleHost"}])
        self.assertEqual(self.distribution["ViewerCertificate"]["AcmCertificateArn"], {"Ref": "ConsoleCertificate"})

    def test_no_amplify_domain_association_is_used(self):
        types = {resource["Type"] for resource in self.resources.values()}
        self.assertNotIn("AWS::Amplify::Domain", types)

    def test_every_path_is_served_by_the_cms_app_and_cli_is_on_the_console_host(self):
        self.assertNotIn("CacheBehaviors", self.distribution, "one default behavior, so /cli/*, /newsroom*, /_next/* and /api/* all reach the CMS")
        behavior = self.distribution["DefaultCacheBehavior"]
        self.assertEqual(behavior["TargetOriginId"], "cms")
        self.assertEqual(sorted(behavior["AllowedMethods"]), sorted(["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]))
        self.assertEqual(behavior["CachePolicyId"], "4135ea2d-6df8-44a3-9df3-4b5a84be39ad", "CachingDisabled")
        self.assertEqual(behavior["OriginRequestPolicyId"], "b689b0a8-53d0-40ab-baf2-68738e2966ac")
        self.assertEqual(behavior["FunctionAssociations"][0]["EventType"], "viewer-request")

    def test_there_is_no_site_bucket_origin_and_no_custom_error_response(self):
        self.assertEqual([origin["Id"] for origin in self.distribution["Origins"]], ["cms"])
        self.assertNotIn("S3OriginConfig", self.distribution["Origins"][0])
        self.assertNotIn("CustomErrorResponses", self.distribution)

    def test_the_viewer_host_is_forwarded_to_the_cms_origin(self):
        code = self.resources["CmsViewerRequestFunction"]["Properties"]["FunctionCode"]["Fn::Sub"]
        self.assertIn('request.headers["x-forwarded-host"]', code)

    def test_dns_alias_records_point_at_the_distribution(self):
        for name, record_type in (("ConsoleAliasIPv4", "A"), ("ConsoleAliasIPv6", "AAAA")):
            properties = self.resources[name]["Properties"]
            self.assertEqual(properties["Type"], record_type)
            self.assertEqual(properties["HostedZoneId"], {"Ref": "HostedZoneId"})
            self.assertEqual(properties["AliasTarget"]["DNSName"], {"Fn::GetAtt": "ConsoleDistribution.DomainName"})
            self.assertEqual(properties["AliasTarget"]["HostedZoneId"], CLOUDFRONT_ALIAS_HOSTED_ZONE)

    def test_the_template_hard_codes_no_account_ids_hosted_zone_ids_or_app_ids(self):
        text = (TEMPLATE_DIRECTORY / "shipped-console.yaml").read_text()
        self.assertNotRegex(text, r"\b\d{12}\b")
        self.assertNotRegex(text, r"\bZ[0-9A-Z]{12,}\b(?<!Z2FDTNDATAQYW2)")


if __name__ == "__main__":
    unittest.main()
