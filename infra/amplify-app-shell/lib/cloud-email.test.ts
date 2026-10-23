import assert from "node:assert/strict";
import { App } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { AmplifyAppShellStack } from "./amplify-app-shell";
import { parseSiteConfig } from "./site-config";

const base = () => ({
  siteId: "example", repository: "https://github.com/example/publication", brand: "example",
  frontend: "markus-static", papyrusVersion: "5.32.0", autoDeploy: false,
  cms: { cognitoDomainPrefix: "example-cms", staging: false,
    environment: { PAPYRUS_OAUTH_REDIRECT_URLS: "http://localhost:3001/" } },
});
function synth(raw: unknown) {
  const app = new App();
  return Template.fromStack(new AmplifyAppShellStack(app, "EmailTest", parseSiteConfig(raw), {
    env: { account: "123456789012", region: "us-east-1" },
  }));
}
const checks: Record<string, () => void> = {
  managed() {
    const template = synth({ ...base(), email: { mode: "managed", sendingDomain: "news.example.test" } });
    template.resourceCountIs("AWS::SES::EmailIdentity", 1);
    template.resourceCountIs("AWS::SES::ConfigurationSet", 1);
    template.resourceCountIs("AWS::Route53::RecordSet", 0);
    template.resourceCountIs("AWS::SES::ReceiptRuleSet", 0);
    template.hasResourceProperties("AWS::SES::EmailIdentity", { EmailIdentity: "news.example.test" });
    template.hasResourceProperties("AWS::SNS::Topic", { TopicName: "papyrus-newsletter-events-example" });
    template.hasResourceProperties("AWS::SES::ConfigurationSetEventDestination", {
      EventDestination: { Name: "cloudwatch-metrics", MatchingEventTypes: ["SEND", "BOUNCE", "COMPLAINT"],
        CloudWatchDestination: { DimensionConfigurations: [{ DimensionName: "ses:configuration-set",
          DimensionValueSource: "MESSAGE_TAG", DefaultDimensionValue: "papyrus-example" }] } },
    });
    const text = JSON.stringify(template.toJSON());
    assert.ok(text.includes("PAPYRUS_EMAIL_FROM_ADDRESS"));
    assert.ok(text.includes("notifications@news.example.test"));
    assert.ok(text.includes("EmailDkimRecord1Name"));
    assert.ok(!text.includes("ses:SendEmail"), "identity setup does not grant unsolicited sending authority");
  },
  existing() {
    const template = synth({ ...base(), email: { mode: "existing", sendingDomain: "news.example.test",
      configurationSet: "already-owned", eventTopicName: "already-owned-events" } });
    template.resourceCountIs("AWS::SES::EmailIdentity", 0);
    template.resourceCountIs("AWS::SES::ConfigurationSet", 0);
    template.resourceCountIs("AWS::SNS::Topic", 0);
    assert.ok(JSON.stringify(template.toJSON()).includes("already-owned"));
  },
  static() {
    const raw: Record<string, unknown> = { ...base(), reader: { buildCommand: "make site", baseDirectory: "dist" } };
    delete raw.cms;
    const template = synth(raw);
    template.resourceCountIs("AWS::SES::EmailIdentity", 0);
    template.resourceCountIs("AWS::SES::ConfigurationSet", 0);
    template.resourceCountIs("AWS::SES::ReceiptRule", 0);
  },
  missing() {
    assert.throws(() => parseSiteConfig(base()), /email.*required.*cloud/i);
    assert.throws(() => parseSiteConfig({ ...base(), email: { mode: "existing", sendingDomain: "news.example.test" } }), /email.configurationSet/);
  },
};
export function runCloudEmailTests(selected?: string): void {
  if (selected) { assert.ok(checks[selected], selected); checks[selected](); }
  else for (const check of Object.values(checks)) check();
  console.log("cloud email infrastructure: ok");
}
