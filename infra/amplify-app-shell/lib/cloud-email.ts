import { ArnFormat, CfnOutput, RemovalPolicy, Stack } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as ses from "aws-cdk-lib/aws-ses";
import * as sns from "aws-cdk-lib/aws-sns";

import type { CloudEmailConfig } from "./cloud-email-config";

/** No DNS mutation, sending grant or receipt activation. Existing identities remain with their owner. */
export function addCloudEmail(stack: Stack, config: CloudEmailConfig): Record<string, string> {
  if (config.mode === "managed") {
    const configurationSet = new ses.CfnConfigurationSet(stack, "CloudEmailConfigurationSet", {
      name: config.configurationSet,
      reputationOptions: { reputationMetricsEnabled: true },
      suppressionOptions: { suppressedReasons: ["BOUNCE", "COMPLAINT"] },
      sendingOptions: { sendingEnabled: true },
    });
    configurationSet.applyRemovalPolicy(RemovalPolicy.RETAIN);
    const identity = new ses.CfnEmailIdentity(stack, "CloudEmailIdentity", {
      emailIdentity: config.sendingDomain,
      dkimSigningAttributes: { nextSigningKeyLength: "RSA_2048_BIT" },
      configurationSetAttributes: { configurationSetName: configurationSet.ref },
    });
    identity.applyRemovalPolicy(RemovalPolicy.RETAIN);
    const topic = new sns.Topic(stack, "CloudEmailEvents", { topicName: config.eventTopicName });
    topic.applyRemovalPolicy(RemovalPolicy.RETAIN);
    topic.addToResourcePolicy(new iam.PolicyStatement({
      principals: [new iam.ServicePrincipal("ses.amazonaws.com")], actions: ["sns:Publish"],
      resources: [topic.topicArn], conditions: { StringEquals: { "aws:SourceAccount": stack.account } },
    }));
    const events = new ses.CfnConfigurationSetEventDestination(stack, "CloudEmailEventDestination", {
      configurationSetName: configurationSet.ref,
      eventDestination: { name: "delivery-events", enabled: true,
        matchingEventTypes: ["SEND", "DELIVERY", "BOUNCE", "COMPLAINT", "REJECT", "RENDERING_FAILURE", "DELIVERY_DELAY"],
        snsDestination: { topicArn: topic.topicArn } },
    });
    events.node.addDependency(topic);
    // These dimensions also feed the newsletter consumer's existing bounce/complaint alarms.
    new ses.CfnConfigurationSetEventDestination(stack, "CloudEmailMetrics", {
      configurationSetName: configurationSet.ref,
      eventDestination: { name: "cloudwatch-metrics", enabled: true,
        matchingEventTypes: ["SEND", "BOUNCE", "COMPLAINT"],
        cloudWatchDestination: { dimensionConfigurations: [{ dimensionName: "ses:configuration-set",
          dimensionValueSource: "MESSAGE_TAG", defaultDimensionValue: config.configurationSet }] } },
    });
    const records = [[identity.attrDkimDnsTokenName1, identity.attrDkimDnsTokenValue1],
      [identity.attrDkimDnsTokenName2, identity.attrDkimDnsTokenValue2],
      [identity.attrDkimDnsTokenName3, identity.attrDkimDnsTokenValue3]];
    records.forEach(([name, value], index) => {
      new CfnOutput(stack, `EmailDkimRecord${index + 1}Name`, { value: name, description: "CNAME name; DNS change requires separate approval" });
      new CfnOutput(stack, `EmailDkimRecord${index + 1}Value`, { value });
    });
  }
  const identityArn = stack.formatArn({ service: "ses", resource: "identity", resourceName: config.sendingDomain, arnFormat: ArnFormat.SLASH_RESOURCE_NAME });
  new CfnOutput(stack, "EmailIdentityArn", { value: identityArn });
  new CfnOutput(stack, "EmailConfigurationSetName", { value: config.configurationSet });
  new CfnOutput(stack, "EmailEventTopicName", { value: config.eventTopicName });
  return { PAPYRUS_EMAIL_FROM_ADDRESS: `${config.senderLocalPart}@${config.sendingDomain}`,
    PAPYRUS_EMAIL_IDENTITY_ARN: identityArn, PAPYRUS_EMAIL_CONFIGURATION_SET: config.configurationSet,
    PAPYRUS_EMAIL_EVENT_TOPIC_NAME: config.eventTopicName };
}
