import { Construct } from "constructs";
import { Stack, StackProps, SecretValue } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as amplify from "aws-cdk-lib/aws-amplify";
import type { AmplifyAppShellSiteConfig } from "../sites/pilobol-us";

/**
 * Provisions the Amplify *app shell* for a Papyrus publication CMS:
 *
 *   - AWS::Amplify::App (WEB_COMPUTE, GitHub repo connection via PAT in Secrets Manager)
 *   - AWS::Amplify::Branch (main, with PAPYRUS_SITE_BRAND env vars)
 *   - AWS::Amplify::Domain (newsroom.<site>.us on the site's Route 53 zone)
 *   - IAM service role (backend deploy) + compute role (SSR rendering)
 *
 * The Papyrus *backend* (AppSync, Storage, Lambda) is NOT created here. It
 * deploys via `ampx pipeline-deploy` from the repo `amplify.yml` once Amplify
 * CI runs a build on the branch. This stack only creates the container the
 * backend deploys into, so the app is never "created manually" in the console.
 *
 * The GitHub access token is read from Secrets Manager by dynamic reference,
 * so the token value never appears in the synthesized template.
 */
export class AmplifyAppShellStack extends Stack {
  public readonly appId: string;
  public readonly defaultDomain: string;

  constructor(scope: Construct, id: string, config: AmplifyAppShellSiteConfig, props?: StackProps) {
    super(scope, id, props);

    const githubToken = SecretValue.secretsManager(config.githubTokenSecretName).unsafeUnwrap();

    // Service role Amplify assumes to deploy the backend (ampx pipeline-deploy
    // creates AppSync, Storage, Lambda, etc., so it needs broad permissions).
    const serviceRole = new iam.Role(this, "AmplifyServiceRole", {
      assumedBy: new iam.ServicePrincipal("amplify.amazonaws.com"),
      description: `Backend deploy service role for Amplify app ${config.appName}`,
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName("AdministratorAccess")],
    });

    // WEB_COMPUTE (Next.js SSR) requires a compute role for the rendering server.
    const computeRole = new iam.Role(this, "AmplifyComputeRole", {
      assumedBy: new iam.ServicePrincipal("amplify.amazonaws.com"),
      description: `SSR compute role for Amplify app ${config.appName}`,
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
        iam.ManagedPolicy.fromAwsManagedPolicyName("CloudWatchLogsFullAccess"),
      ],
    });

    const app = new amplify.CfnApp(this, "App", {
      name: config.appName,
      description: config.description,
      platform: config.platform,
      repository: config.repository,
      accessToken: githubToken,
      iamServiceRole: serviceRole.roleArn,
      computeRoleArn: computeRole.roleArn,
      buildSpec: this.buildSpec(),
      customRules: [{ source: "/<*>", target: "/index.html", status: "404-200" }],
    });

    this.appId = app.attrAppId;
    this.defaultDomain = `${app.attrAppId}.amplifyapp.com`;

    const branch = new amplify.CfnBranch(this, "Branch", {
      appId: app.attrAppId,
      branchName: config.branchName,
      stage: "PRODUCTION",
      enableAutoBuild: config.enableAutoBuild ?? true,
      enablePerformanceMode: false,
      environmentVariables: Object.entries(config.environment).map(([key, value]) => ({
        name: key,
        value,
      })),
    });
    branch.addResourceDependency(app);

    const domain = new amplify.CfnDomain(this, "Domain", {
      appId: app.attrAppId,
      domainName: config.domainName,
      subDomainSettings: [{ branchName: config.branchName, prefix: "" }],
    });
    domain.addResourceDependency(branch);

    this.exportValue(app.attrAppId, { description: `Amplify app id for ${config.appName}` });
  }

  /**
   * Build spec mirrors the repo root amplify.yml so the app deploys the full
   * Papyrus backend + Next.js frontend on every build. Inlined because Amplify
   * needs a buildSpec on the app for the first deploy before the repo is cloned.
   */
  private buildSpec(): string {
    return [
      "version: 1",
      "backend:",
      "  phases:",
      "    build:",
      "      commands:",
      "        - npm install --cache .npm --prefer-offline",
      "        - |",
      "          if [ -z \"${PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI:-}\" ]; then",
      "            export PAPYRUS_CONSOLE_RESPONDER_ALLOW_LOCAL_BUILD=true",
      "          fi",
      "        - npx ampx pipeline-deploy --debug --branch $AWS_BRANCH --app-id $AWS_APP_ID",
      "frontend:",
      "  phases:",
      "    build:",
      "      commands:",
      "        - env | grep -e '^PAPYRUS_CONTENT_SOURCE=' -e '^PAPYRUS_EDITION_SLUG=' -e '^PAPYRUS_REVALIDATE_SECRET=' >> .env.production",
      "        - npm run build",
      "  artifacts:",
      "    baseDirectory: .next",
      "    files:",
      "      - '**/*'",
      "  cache:",
      "    paths:",
      "      - .next/cache/**/*",
      "      - .npm/**/*",
    ].join("\n");
  }
}
