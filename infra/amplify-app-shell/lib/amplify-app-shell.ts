import { Construct } from "constructs";
import { ArnFormat, CfnOutput, Duration, Fn, Stack, StackProps } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as amplify from "aws-cdk-lib/aws-amplify";
import { GITHUB_OIDC_PROVIDER_HOST } from "./github-oidc-provider";
import { cmsProductionBuildSpec, cmsStagingBuildSpec, readerBuildSpec } from "./build-specs";
import { AmplifyAppShellSiteConfig, isStagingEnabled, resolveStackName, resolveStagingDomainName, resolveStoragePreviewPrefix } from "./site-config";

function environmentVariables(variables: Record<string, string>): amplify.CfnBranch.EnvironmentVariableProperty[] {
  return Object.entries(variables).map(([name, value]) => ({ name, value }));
}

/**
 * Provisions the Amplify *app shell* of a Papyrus publication from its
 * site.json:
 *
 *   - CMS app (WEB_COMPUTE) with branches `main` (production, owns the backend)
 *     and `staging` (frontend only, reads the production backend)
 *   - for `markus-static` sites, a reader app (WEB) with branch `main`
 *   - a domain association per branch/app when a domain is configured (without
 *     one, no AWS::Amplify::Domain is created and the default amplifyapp.com
 *     URL is used), IAM service and compute roles
 *   - `cms.staging: false` omits the staging branch and its domain
 *
 * The stack also creates the `<siteId>-papyrus-authoring` role. The CLI signs
 * AppSync requests (SigV4) with credentials for that role (SSO, OIDC or any
 * principal in the account that may assume it); no token is stored anywhere.
 *
 * No repository and no access token are configured: the apps are manual-deploy
 * until Amplify's GitHub App is connected once in the console
 * (docs/site-hosting.md). The Papyrus backend itself is created inside the CMS
 * app by `ampx pipeline-deploy` from the production build.
 */
export class AmplifyAppShellStack extends Stack {
  public readonly cmsAppId: string;
  public readonly readerAppId?: string;

  constructor(scope: Construct, id: string, config: AmplifyAppShellSiteConfig, props?: StackProps) {
    super(scope, id, props);

    const cmsAppName = config.cms.appName ?? `${config.siteId}-cms`;
    const stagingEnabled = isStagingEnabled(config);
    const stagingDomainName = resolveStagingDomainName(config);

    const cmsServiceRole = new iam.Role(this, "AmplifyServiceRole", {
      assumedBy: new iam.ServicePrincipal("amplify.amazonaws.com"),
      description: `Backend deploy and staging build service role for Amplify app ${cmsAppName} (AdministratorAccess: documented risk)`,
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName("AdministratorAccess")],
    });

    const computeRole = new iam.Role(this, "AmplifyComputeRole", {
      assumedBy: new iam.ServicePrincipal("amplify.amazonaws.com"),
      description: `SSR compute role for Amplify app ${cmsAppName}`,
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
        iam.ManagedPolicy.fromAwsManagedPolicyName("CloudWatchLogsFullAccess"),
      ],
    });

    const cmsApp = new amplify.CfnApp(this, "App", {
      name: cmsAppName,
      description: `Papyrus newsroom CMS for ${config.siteId} (WEB_COMPUTE)`,
      platform: "WEB_COMPUTE",
      iamServiceRole: cmsServiceRole.roleArn,
      computeRoleArn: computeRole.roleArn,
      buildSpec: cmsProductionBuildSpec(config),
      jobConfig: config.cms.buildComputeType ? { buildComputeType: config.cms.buildComputeType } : undefined,
      customRules: [{ source: "/<*>", target: "/index.html", status: "404-200" }],
    });

    const stagingMode: Record<string, string> = config.frontend === "markus-static"
      ? { PAPYRUS_STAGING_PREVIEW: "static" }
      : { PAPYRUS_CONTENT_SOURCE: "drafts" };

    const productionOrigin = config.cms.domainName
      ? `https://${config.cms.domainName}/`
      : Fn.join("", ["https://main.", cmsApp.attrDefaultDomain, "/"]);
    const stagingOrigin = stagingDomainName
      ? `https://${stagingDomainName}/`
      : Fn.join("", ["https://staging.", cmsApp.attrDefaultDomain, "/"]);
    const defaultOriginsToAllow = [
      ...(config.cms.domainName ? [] : [productionOrigin]),
      ...(stagingEnabled && !stagingDomainName ? [stagingOrigin] : []),
    ];
    const oauthRedirectUrls = defaultOriginsToAllow.length === 0
      ? config.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS
      : Fn.join(",", [config.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS, ...defaultOriginsToAllow]);

    const productionBranch = new amplify.CfnBranch(this, "Branch", {
      appId: cmsApp.attrAppId,
      branchName: "main",
      stage: "PRODUCTION",
      enableAutoBuild: true,
      enablePerformanceMode: false,
      environmentVariables: environmentVariables({
        ...config.cms.environment,
        PAPYRUS_OAUTH_REDIRECT_URLS: oauthRedirectUrls,
        PAPYRUS_SITE_BRAND: config.brand,
        SITE_ENV: "production",
        PAPYRUS_CONTENT_SOURCE: "published",
      }),
    });

    if (stagingEnabled) {
      const stagingBranch = new amplify.CfnBranch(this, "StagingBranch", {
        appId: cmsApp.attrAppId,
        branchName: "staging",
        stage: "BETA",
        enableAutoBuild: true,
        enablePerformanceMode: false,
        buildSpec: cmsStagingBuildSpec(config),
        environmentVariables: environmentVariables({
          ...config.cms.environment,
          PAPYRUS_OAUTH_REDIRECT_URLS: oauthRedirectUrls,
          PAPYRUS_SITE_BRAND: config.brand,
          SITE_ENV: "staging",
          ...stagingMode,
          NEXT_PUBLIC_PAPYRUS_STAGING_URL: stagingDomainName
            ? `https://${stagingDomainName}`
            : Fn.join("", ["https://staging.", cmsApp.attrDefaultDomain]),
        }),
      });

      if (stagingDomainName) {
        const stagingDomain = new amplify.CfnDomain(this, "StagingDomain", {
          appId: cmsApp.attrAppId,
          domainName: stagingDomainName,
          subDomainSettings: [{ branchName: "staging", prefix: "" }],
        });
        stagingDomain.addResourceDependency(stagingBranch);
      }
    }

    if (config.cms.domainName) {
      const productionDomain = new amplify.CfnDomain(this, "Domain", {
        appId: cmsApp.attrAppId,
        domainName: config.cms.domainName,
        subDomainSettings: [{ branchName: "main", prefix: "" }],
      });
      productionDomain.addResourceDependency(productionBranch);
    }

    this.cmsAppId = cmsApp.attrAppId;
    new CfnOutput(this, "CmsAppId", { value: cmsApp.attrAppId, description: `Amplify app id for ${cmsAppName}` });
    new CfnOutput(this, "CmsOrigin", { value: productionOrigin });
    if (stagingEnabled) {
      new CfnOutput(this, "StagingOrigin", { value: stagingOrigin });
    }

    if (config.reader) {
      this.readerAppId = this.addReaderApp(config, config.reader);
    }

    const amplifyAppIds = [cmsApp.attrAppId, ...(this.readerAppId ? [this.readerAppId] : [])];
    this.addAuthoringRole(config, cmsApp.attrAppId, amplifyAppIds);

    if (config.github) {
      this.addGithubCiRole(config, config.github, amplifyAppIds);
    }
  }

  private authoringStatements(config: AmplifyAppShellSiteConfig, cmsAppId: string, amplifyAppIds: string[]): iam.PolicyStatement[] {
    const mediaBucketArn = `arn:${this.partition}:s3:::amplify-${cmsAppId}-*`;
    return [
      new iam.PolicyStatement({
        sid: "SignAppSyncAuthoringRequests",
        actions: ["appsync:GraphQL"],
        resources: ["Query", "Mutation"].map((typeName) =>
          this.formatArn({ service: "appsync", resource: "apis", resourceName: `*/types/${typeName}/fields/*`, arnFormat: ArnFormat.SLASH_RESOURCE_NAME }),
        ),
      }),
      new iam.PolicyStatement({
        sid: "ReadWriteMediaAndPreview",
        actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
        resources: [`${mediaBucketArn}/media/*`, `${mediaBucketArn}/${resolveStoragePreviewPrefix(config)}*`],
      }),
      new iam.PolicyStatement({
        sid: "ListMediaAndPreview",
        actions: ["s3:ListBucket"],
        resources: [mediaBucketArn],
        conditions: { StringLike: { "s3:prefix": ["media/*", `${resolveStoragePreviewPrefix(config)}*`] } },
      }),
      new iam.PolicyStatement({
        sid: "StartAndInspectAmplifyJobs",
        actions: ["amplify:StartJob", "amplify:ListJobs", "amplify:GetJob", "amplify:ListBranches"],
        resources: amplifyAppIds.flatMap((appId) => [
          this.formatArn({ service: "amplify", resource: "apps", resourceName: appId, arnFormat: ArnFormat.SLASH_RESOURCE_NAME }),
          this.formatArn({ service: "amplify", resource: "apps", resourceName: `${appId}/*`, arnFormat: ArnFormat.SLASH_RESOURCE_NAME }),
        ]),
      }),
    ];
  }

  private addAuthoringRole(config: AmplifyAppShellSiteConfig, cmsAppId: string, amplifyAppIds: string[]): void {
    const authoringRole = new iam.Role(this, "PapyrusAuthoringRole", {
      roleName: `${config.siteId}-papyrus-authoring`,
      description: `Papyrus CLI authoring role for ${config.siteId}: AppSync (SigV4), media and preview storage, rebuild jobs. Assumable by principals in this account that are allowed sts:AssumeRole on it.`,
      assumedBy: new iam.AccountRootPrincipal(),
    });
    for (const statement of this.authoringStatements(config, cmsAppId, amplifyAppIds)) {
      authoringRole.addToPolicy(statement);
    }
    new CfnOutput(this, "PapyrusAuthoringRoleArn", {
      value: authoringRole.roleArn,
      description: `Role the Papyrus CLI assumes for ${config.siteId} (profile role_arn)`,
    });
  }

  private addGithubCiRole(
    config: AmplifyAppShellSiteConfig,
    github: NonNullable<AmplifyAppShellSiteConfig["github"]>,
    amplifyAppIds: string[],
  ): void {
    const provider = iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(
      this,
      "GithubOidcProvider",
      this.formatArn({
        service: "iam",
        region: "",
        resource: "oidc-provider",
        resourceName: GITHUB_OIDC_PROVIDER_HOST,
        arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
      }),
    );

    const ciRole = new iam.Role(this, "GithubCiRole", {
      roleName: `${config.siteId}-github-ci`,
      description: `GitHub Actions role for ${github.owner}/${github.repo} (OIDC, least privilege, no admin policy)`,
      maxSessionDuration: Duration.hours(1),
      assumedBy: new iam.OpenIdConnectPrincipal(provider, {
        StringEquals: { [`${GITHUB_OIDC_PROVIDER_HOST}:aud`]: "sts.amazonaws.com" },
        StringLike: {
          [`${GITHUB_OIDC_PROVIDER_HOST}:sub`]: github.branches.map(
            (branch) => `repo:${github.owner}/${github.repo}:ref:refs/heads/${branch}`,
          ),
        },
      }),
    });

    for (const statement of this.authoringStatements(config, this.cmsAppId, amplifyAppIds)) {
      ciRole.addToPolicy(statement);
    }
    ciRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "WhoAmI",
        actions: ["sts:GetCallerIdentity"],
        resources: ["*"],
      }),
    );
    if (github.ciCanDeployInfra) {
      ciRole.addToPolicy(
        new iam.PolicyStatement({
          sid: "DeployThisSitesAppShellStack",
          actions: ["cloudformation:*"],
          resources: [
            this.formatArn({ service: "cloudformation", resource: "stack", resourceName: `${resolveStackName(config)}/*`, arnFormat: ArnFormat.SLASH_RESOURCE_NAME }),
          ],
        }),
      );
    }

    new CfnOutput(this, "GithubCiRoleArn", { value: ciRole.roleArn, description: `Role for GitHub Actions in ${github.owner}/${github.repo}` });
  }

  private addReaderApp(
    config: AmplifyAppShellSiteConfig,
    reader: NonNullable<AmplifyAppShellSiteConfig["reader"]>,
  ): string {
    const readerAppName = reader.appName ?? `${config.siteId}-reader`;
    const readerBranchName = reader.branchName ?? "main";

    const readerServiceRole = new iam.Role(this, "ReaderServiceRole", {
      assumedBy: new iam.ServicePrincipal("amplify.amazonaws.com"),
      description: `Static reader build role for Amplify app ${readerAppName} (reads published media only; content is read as a Cognito guest)`,
    });
    readerServiceRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "ReadMediaForExport",
        actions: ["s3:GetObject"],
        resources: ["arn:aws:s3:::amplify-*/media/*"],
      }),
    );

    const readerApp = new amplify.CfnApp(this, "ReaderApp", {
      name: readerAppName,
      description: `Papyrus static reader for ${config.siteId} (WEB)`,
      platform: "WEB",
      iamServiceRole: readerServiceRole.roleArn,
      buildSpec: readerBuildSpec(config),
    });

    const readerBranch = new amplify.CfnBranch(this, "ReaderBranch", {
      appId: readerApp.attrAppId,
      branchName: readerBranchName,
      stage: "PRODUCTION",
      enableAutoBuild: true,
      environmentVariables: environmentVariables({
        ...(reader.environment ?? {}),
        PAPYRUS_SITE_BRAND: config.brand,
        SITE_ENV: "production",
      }),
    });

    if (reader.domainName) {
      const readerDomain = new amplify.CfnDomain(this, "ReaderDomain", {
        appId: readerApp.attrAppId,
        domainName: reader.domainName,
        subDomainSettings: [{ branchName: readerBranchName, prefix: "" }],
      });
      readerDomain.addResourceDependency(readerBranch);
    }

    new CfnOutput(this, "ReaderAppId", { value: readerApp.attrAppId, description: `Amplify app id for ${readerAppName}` });
    new CfnOutput(this, "ReaderOrigin", {
      value: reader.domainName
        ? `https://${reader.domainName}/`
        : Fn.join("", [`https://${readerBranchName}.`, readerApp.attrDefaultDomain, "/"]),
    });
    return readerApp.attrAppId;
  }
}
