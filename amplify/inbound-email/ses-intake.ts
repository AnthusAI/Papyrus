import { Duration } from "aws-cdk-lib";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as ses from "aws-cdk-lib/aws-ses";
import * as sesActions from "aws-cdk-lib/aws-ses-actions";
import type * as s3 from "aws-cdk-lib/aws-s3";
import { AwsCustomResource, AwsCustomResourcePolicy, PhysicalResourceId } from "aws-cdk-lib/custom-resources";
import type { Construct } from "constructs";

export type InboundEmailSesIntakeProps = {
  storageBucket: s3.IBucket;
  recipients: string[];
  ruleSetName: string;
  /** Adds the rule to a rule set another stack owns instead of creating one. */
  existingRuleSetName?: string;
  /** `undefined` lets CloudFormation generate the name (the live p.apyr.us rule). */
  ruleName?: string;
  /** Only the legacy p.apyr.us pipeline sets this; a new site never activates a rule set. */
  activateRuleSet: boolean;
  domainIdentity?: {
    domain: string;
    hostedZoneId: string;
    hostedZoneName: string;
    recordName: string;
  };
};

/**
 * Adds the SES receipt resources directly to `scope` (no wrapper construct) so
 * the logical ids of the live p.apyr.us stack stay unchanged.
 */
export function addInboundEmailSesIntake(scope: Construct, props: InboundEmailSesIntakeProps) {
  if (props.domainIdentity) {
    const { domain, hostedZoneId, hostedZoneName, recordName } = props.domainIdentity;
    const zone = route53.HostedZone.fromHostedZoneAttributes(scope, "PapyrusInboundDnsZone", {
      hostedZoneId,
      zoneName: hostedZoneName,
    });
    const verifyDomain = new AwsCustomResource(scope, "VerifyInboundEmailDomain", {
      onCreate: {
        service: "SES",
        action: "verifyDomainIdentity",
        parameters: { Domain: domain },
        physicalResourceId: PhysicalResourceId.of(`ses-domain-verify-${domain}`),
      },
      onUpdate: {
        service: "SES",
        action: "verifyDomainIdentity",
        parameters: { Domain: domain },
        physicalResourceId: PhysicalResourceId.of(`ses-domain-verify-${domain}`),
      },
      policy: AwsCustomResourcePolicy.fromSdkCalls({
        resources: AwsCustomResourcePolicy.ANY_RESOURCE,
      }),
      timeout: Duration.minutes(2),
    });
    new route53.TxtRecord(scope, "PapyrusInboundEmailDomainVerification", {
      zone,
      recordName: `_amazonses.${recordName}`,
      ttl: Duration.minutes(5),
      values: [verifyDomain.getResponseField("VerificationToken")],
    });
  }

  const ruleSet = props.existingRuleSetName
    ? ses.ReceiptRuleSet.fromReceiptRuleSetName(scope, "PapyrusInboundEmailRuleSet", props.existingRuleSetName)
    : new ses.ReceiptRuleSet(scope, "PapyrusInboundEmailRuleSet", {
        receiptRuleSetName: props.ruleSetName,
      });
  ruleSet.addRule("PapyrusInboundSubmissions", {
    receiptRuleName: props.ruleName,
    recipients: props.recipients,
    enabled: true,
    scanEnabled: true,
    tlsPolicy: ses.TlsPolicy.REQUIRE,
    actions: [
      new sesActions.S3({
        bucket: props.storageBucket,
        objectKeyPrefix: "inbound-email/",
      }),
    ],
  });

  if (props.activateRuleSet && !props.existingRuleSetName) {
    new AwsCustomResource(scope, "ActivateInboundEmailRuleSet", {
      onCreate: {
        service: "SES",
        action: "setActiveReceiptRuleSet",
        parameters: { RuleSetName: ruleSet.receiptRuleSetName },
        physicalResourceId: PhysicalResourceId.of(`activate-${ruleSet.receiptRuleSetName}`),
      },
      onUpdate: {
        service: "SES",
        action: "setActiveReceiptRuleSet",
        parameters: { RuleSetName: ruleSet.receiptRuleSetName },
        physicalResourceId: PhysicalResourceId.of(`activate-${ruleSet.receiptRuleSetName}`),
      },
      onDelete: {
        service: "SES",
        action: "setActiveReceiptRuleSet",
        parameters: { RuleSetName: null },
      },
      policy: AwsCustomResourcePolicy.fromSdkCalls({
        resources: AwsCustomResourcePolicy.ANY_RESOURCE,
      }),
      timeout: Duration.minutes(2),
    });
  }

  return { ruleSet };
}
