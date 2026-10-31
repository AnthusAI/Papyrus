import { Construct } from "constructs";
import { ArnFormat, CfnOutput, Duration, Fn, Stack, StackProps } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as amplify from "aws-cdk-lib/aws-amplify";
import { SecureStringParameter } from "./secure-string-parameter";
import { addCloudEmail } from "./cloud-email";
import { parseCloudEmail } from "./cloud-email-config";
import { GITHUB_OIDC_PROVIDER_HOST } from "./github-oidc-provider";
import { cmsProductionBuildSpec, cmsStagingBuildSpec, readerBuildSpec } from "./build-specs";
import { AmplifyAppShellSiteConfig, PROSPECTUS_PAPYRUS_SITE_ROUTES, ReaderCustomHeaderRule, hasCmsApp, isStagingEnabled, resolveRedirectSubDomainPrefix, resolveCmsHostName, resolveSiteOrigin, githubOidcSubjects, resolveGithubRepository, resolveProspectusAccountsEndpoint, resolveProspectusSessionSealingParameterName, resolveReaderPollSecretParameterName, resolveRevalidateSecretParameterName, resolveStackName, resolveStagingDomainName, resolveChatStackName, chatExportName, CHAT_EXPORTED_RESOURCES, CHAT_ENVIRONMENT_NAMES, CHAT_PRIVATE_ASSISTANT_ID, CHAT_PRIVATE_ASSISTANT_NAME, resolveStoragePreviewPrefix } from "./site-config";

function environmentVariables(variables: Record<string, string>): amplify.CfnBranch.EnvironmentVariableProperty[] {
  return Object.entries(variables).map(([name, value]) => ({ name, value }));
}

/**
 * The production branch's private chat environment. Only a site with an enabled `chat` block gets the flag and the
 * resource names (imported from the chat data stack's exports, so that stack must be deployed first); every other
 * site keeps the flag "false" and no chat variables, and its newsroom serves neither the chat route nor the UI.
 */
function chatEnvironment(config: AmplifyAppShellSiteConfig): Record<string, string> {
  const chatStackName = resolveChatStackName(config);
  if (!chatStackName) return { PAPYRUS_PRIVATE_CHAT_ENABLED: "false" };
  return {
    PAPYRUS_PRIVATE_CHAT_ENABLED: "true",
    ...Object.fromEntries(CHAT_EXPORTED_RESOURCES.map((resource) => [CHAT_ENVIRONMENT_NAMES[resource], Fn.importValue(chatExportName(chatStackName, resource))])),
    PAPYRUS_CHAT_PRIVATE_BOT_ID: CHAT_PRIVATE_ASSISTANT_ID,
    PAPYRUS_CHAT_PRIVATE_BOT_NAME: CHAT_PRIVATE_ASSISTANT_NAME,
  };
}

function readerCustomHeaders(rules: ReaderCustomHeaderRule[] | undefined): string | undefined {
  if (!rules) return undefined;
  const lines = ["customHeaders:"];
  for (const rule of rules) {
    lines.push(`  - pattern: ${JSON.stringify(rule.pattern)}`, "    headers:");
    for (const [key, value] of Object.entries(rule.headers)) {
      lines.push(`      - key: ${JSON.stringify(key)}`, `        value: ${JSON.stringify(value)}`);
    }
  }
  return lines.join("\n") + "\n";
}

/**
 * Provisions the Amplify *app shell* of a Papyrus publication from its
 * site.json:
 *
 *   - CMS app (WEB_COMPUTE) with branches `main` (production, owns the backend)
 *     and `staging` (frontend only, reads the production backend)
 *   - for `markus-static` sites, a reader app (WEB) with branch `main`; a
 *     `markus-static` site may omit `cms` to get the reader app alone (no CMS
 *     app, no CMS roles, no authoring role)
 *   - a domain association per branch/app when a domain is configured (without
 *     one, no AWS::Amplify::Domain is created and the default amplifyapp.com
 *     URL is used), IAM service and compute roles
 *   - `cms.staging: false` omits the staging branch and its domain
 *
 * Google sign-in is always on: the branches never set PAPYRUS_DISABLE_GOOGLE_OAUTH,
and `cms.cognitoDomainPrefix` becomes the hosted-UI domain
(PAPYRUS_COGNITO_DOMAIN_PREFIX) only when `cms.applyCognitoDomainPrefix` is true
(PAPYRUS_APPLY_COGNITO_DOMAIN_PREFIX); otherwise Amplify's generated domain is kept. The secrets GOOGLE_CLIENT_ID and
GOOGLE_CLIENT_SECRET are Amplify backend secrets set in the console, never here.
The stack also creates the `<siteId>-papyrus-authoring` role. The CLI signs
 * AppSync requests (SigV4) with credentials for that role (SSO, OIDC or any
 * principal in the account that may assume it); no token is stored anywhere.
 *
 * Unless `repositoryAccessTokenSecretArn` is set, no repository and no access
 * token are configured: the apps are manual-deploy until Amplify's GitHub App is
 * connected once in the console (docs/site-hosting.md). When it is set, both apps
 * are created against `repository` and read the GitHub token from that Secrets
 * Manager secret through a CloudFormation dynamic reference, so the token never
 * appears in site.json or the synthesized template. The Papyrus backend itself is created inside the CMS
 * app by `ampx pipeline-deploy` from the production build.
 */
function repositoryConnectionProperties(config: AmplifyAppShellSiteConfig): { repository?: string; accessToken?: string } {
  if (config.repositoryAccessTokenSecretArn === undefined) return {};
  return {
    repository: config.repository,
    accessToken: `{{resolve:secretsmanager:${config.repositoryAccessTokenSecretArn}:SecretString}}`,
  };
}

export class AmplifyAppShellStack extends Stack {
  public readonly cmsAppId?: string;
  public readonly readerAppId?: string;

  constructor(scope: Construct, id: string, config: AmplifyAppShellSiteConfig, props?: StackProps) {
    super(scope, id, props);

    if (!hasCmsApp(config)) {
      if (!config.reader) throw new Error(`site ${config.siteId} has neither a cms section nor a reader`);
      this.readerAppId = this.addReaderApp(config, config.reader);
      if (config.autoDeploy) {
        this.addGithubDeployRole(config, [{ appId: this.readerAppId, branch: config.reader.branchName ?? "main" }]);
      }
      return;
    }

    const cmsAppName = config.cms.appName ?? `${config.siteId}-cms`;
    const emailEnvironment = addCloudEmail(this, parseCloudEmail(config.email, true, config.siteId)!);
    const stagingEnabled = isStagingEnabled(config);
    const stagingDomainName = resolveStagingDomainName(config);
    const cmsHostName = resolveCmsHostName(config);

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

    const revalidateSecretParameterName = config.frontend === "pretext" ? resolveRevalidateSecretParameterName(config) : undefined;
    if (revalidateSecretParameterName) {
      const revalidateSecret = new SecureStringParameter(this, "RevalidateSecretParameter", {
        parameterName: revalidateSecretParameterName,
        description: `Shared secret that authorizes publishes to call the /api/revalidate route of ${cmsAppName}`,
      });
      computeRole.addToPolicy(
        new iam.PolicyStatement({
          sid: "ReadRevalidateSecret",
          actions: ["ssm:GetParameter"],
          resources: [revalidateSecret.parameterArn],
        }),
      );
    }

    const prospectusAccountsApiStageArn = config.cms.prospectusAccountsApiStageArn;
    const prospectusSessionSealing = prospectusAccountsApiStageArn
      ? new SecureStringParameter(this, "ProspectusSessionSealingParameter", {
        parameterName: resolveProspectusSessionSealingParameterName(config),
        description: `Seals the Prospectus sign-in cookies of ${cmsAppName}; replacing it signs everyone out`,
      })
      : undefined;
    const prospectusEnvironment: Record<string, string> = prospectusAccountsApiStageArn && prospectusSessionSealing
      ? {
        PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT: resolveProspectusAccountsEndpoint(prospectusAccountsApiStageArn),
        PAPYRUS_PROSPECTUS_SESSION_SECRET_PARAMETER: prospectusSessionSealing.parameterName,
        PAPYRUS_PROSPECTUS_SITE_PRODUCT: `papyrus-${config.siteId}`,
      }
      : {};
    if (prospectusSessionSealing) {
      computeRole.addToPolicy(
        new iam.PolicyStatement({
          sid: "ReadProspectusSessionSealingSecret",
          actions: ["ssm:GetParameter"],
          resources: [prospectusSessionSealing.parameterArn],
        }),
      );
    }
    if (prospectusAccountsApiStageArn && config.cms.readerRetirementPoll) {
      // Prospectus admits one caller per site, this compute role, so the scheduled snapshot run reaches the retired-subject
      // route through the CMS route /api/reader/retired, which it authenticates with this secret.
      const readerPollSecret = new SecureStringParameter(this, "ReaderPollSecretParameter", {
        parameterName: resolveReaderPollSecretParameterName(config),
        description: `Authorizes the scheduled reader snapshot run to call the retired-subject route of ${cmsAppName}`,
      });
      prospectusEnvironment.PAPYRUS_READER_POLL_SECRET_PARAMETER = readerPollSecret.parameterName;
      computeRole.addToPolicy(
        new iam.PolicyStatement({
          sid: "ReadReaderPollSecret",
          actions: ["ssm:GetParameter"],
          resources: [readerPollSecret.parameterArn],
        }),
      );
    }
    if (prospectusAccountsApiStageArn) {
      computeRole.addToPolicy(
        new iam.PolicyStatement({
          sid: "InvokeProspectusAccountsAsRegisteredSite",
          actions: ["execute-api:Invoke"],
          resources: PROSPECTUS_PAPYRUS_SITE_ROUTES.map((route) => `${prospectusAccountsApiStageArn}/${route}`),
        }),
      );
    }

    const repositoryConnection = repositoryConnectionProperties(config);

    const cmsApp = new amplify.CfnApp(this, "App", {
      ...repositoryConnection,
      name: cmsAppName,
      description: `Papyrus newsroom CMS for ${config.siteId} (WEB_COMPUTE)`,
      platform: "WEB_COMPUTE",
      iamServiceRole: cmsServiceRole.roleArn,
      computeRoleArn: computeRole.roleArn,
      buildSpec: cmsProductionBuildSpec(config),
      jobConfig: config.cms.buildComputeType ? { buildComputeType: config.cms.buildComputeType } : undefined,
      customRules: [
        ...(config.cms.redirects ?? []).map((redirect) => ({
          source: `https://${redirect.source}`,
          target: `https://${resolveCmsHostName(config)}`,
          status: String(redirect.status),
        })),
        { source: "/<*>", target: "/index.html", status: "404-200" },
      ],
    });

    const stagingMode: Record<string, string> = config.frontend === "markus-static"
      ? { PAPYRUS_STAGING_PREVIEW: "static" }
      : { PAPYRUS_CONTENT_SOURCE: "drafts" };

    const productionOrigin = cmsHostName
      ? `https://${cmsHostName}/`
      : Fn.join("", ["https://main.", cmsApp.attrDefaultDomain, "/"]);
    const stagingOrigin = stagingDomainName
      ? `https://${stagingDomainName}/`
      : Fn.join("", ["https://staging.", cmsApp.attrDefaultDomain, "/"]);
    // The compute adapter's request URL is https://localhost:3000, so the site names its own public origin.
    // A site served by its own edge (cms.siteOrigin) has no Amplify domain, so the edge host is its origin.
    const siteOrigin = resolveSiteOrigin(config);
    const productionSiteOrigin = cmsHostName ? `https://${cmsHostName}` : siteOrigin ?? Fn.join("", ["https://main.", cmsApp.attrDefaultDomain]);
    const stagingSiteOrigin = stagingDomainName ? `https://${stagingDomainName}` : Fn.join("", ["https://staging.", cmsApp.attrDefaultDomain]);
    const sharedRootDomain = config.cms.domainPrefix !== undefined;
    const defaultOriginsToAllow = [
      ...(config.cms.domainName ? [] : [productionOrigin]),
      ...(siteOrigin ? [`${siteOrigin}/`] : []),
      ...(stagingEnabled && !stagingDomainName ? [stagingOrigin] : []),
    ];
    const oauthRedirectUrls = defaultOriginsToAllow.length === 0
      ? config.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS
      : Fn.join(",", [config.cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS, ...defaultOriginsToAllow]);

    const productionBranch = new amplify.CfnBranch(this, "Branch", {
      appId: cmsApp.attrAppId,
      branchName: "main",
      stage: "PRODUCTION",
      // Auto-build off when GitHub Actions starts the job on merge (autoDeploy): nothing may double-build.
      enableAutoBuild: !config.autoDeploy,
      enablePerformanceMode: false,
      environmentVariables: environmentVariables({
        ...config.cms.environment,
        ...emailEnvironment,
        ...(config.chat?.enabled ? chatEnvironment(config) : { PAPYRUS_PRIVATE_CHAT_ENABLED: config.cms.environment.PAPYRUS_PRIVATE_CHAT_ENABLED ?? "false" }),
        PAPYRUS_COGNITO_DOMAIN_PREFIX: config.cms.cognitoDomainPrefix,
        ...(config.cms.applyCognitoDomainPrefix ? { PAPYRUS_APPLY_COGNITO_DOMAIN_PREFIX: "true" } : {}),
        PAPYRUS_OAUTH_REDIRECT_URLS: oauthRedirectUrls,
        PAPYRUS_SITE_BRAND: config.brand,
        SITE_ENV: "production",
        PAPYRUS_SITE_ORIGIN: productionSiteOrigin,
        PAPYRUS_CONTENT_SOURCE: "published",
        ...(config.cms.cliRemoteLogin
          ? { PAPYRUS_ENABLE_CLI_REMOTE_LOGIN: "true", PAPYRUS_CLI_INVOKER_ROLE_ARN: computeRole.roleArn }
          : {}),
        ...(config.cms.cliOnFederationClient ? { PAPYRUS_ENABLE_CLI_ON_FEDERATION_CLIENT: "true" } : {}),
        ...(revalidateSecretParameterName ? { PAPYRUS_REVALIDATE_SECRET_PARAMETER: revalidateSecretParameterName } : {}),
        ...prospectusEnvironment,
      }),
    });

    let stagingBranch: amplify.CfnBranch | undefined;
    if (stagingEnabled) {
      stagingBranch = new amplify.CfnBranch(this, "StagingBranch", {
        appId: cmsApp.attrAppId,
        branchName: "staging",
        stage: "BETA",
        enableAutoBuild: true,
        enablePerformanceMode: false,
        buildSpec: cmsStagingBuildSpec(config),
        environmentVariables: environmentVariables({
          ...config.cms.environment,
          PAPYRUS_PRIVATE_CHAT_ENABLED: "false",
          PAPYRUS_COGNITO_DOMAIN_PREFIX: config.cms.cognitoDomainPrefix,
          ...(config.cms.applyCognitoDomainPrefix ? { PAPYRUS_APPLY_COGNITO_DOMAIN_PREFIX: "true" } : {}),
          PAPYRUS_OAUTH_REDIRECT_URLS: oauthRedirectUrls,
          PAPYRUS_SITE_BRAND: config.brand,
          SITE_ENV: "staging",
          PAPYRUS_SITE_ORIGIN: stagingSiteOrigin,
          ...stagingMode,
          ...prospectusEnvironment,
          NEXT_PUBLIC_PAPYRUS_STAGING_URL: stagingDomainName
            ? `https://${stagingDomainName}`
            : Fn.join("", ["https://staging.", cmsApp.attrDefaultDomain]),
        }),
      });

      if (stagingDomainName && !sharedRootDomain) {
        const stagingDomain = new amplify.CfnDomain(this, "StagingDomain", {
          appId: cmsApp.attrAppId,
          domainName: stagingDomainName,
          subDomainSettings: [{ branchName: "staging", prefix: "" }],
        });
        stagingDomain.addResourceDependency(stagingBranch);
      }
    }

    if (config.cms.domainName) {
      const subDomainSettings = sharedRootDomain
        ? [
            { branchName: "main", prefix: config.cms.domainPrefix as string },
            ...(config.cms.redirects ?? []).map((redirect) => ({
              branchName: "main",
              prefix: resolveRedirectSubDomainPrefix(config.cms.domainName as string, redirect.source),
            })),
            ...(stagingBranch ? [{ branchName: "staging", prefix: config.cms.stagingDomainPrefix as string }] : []),
          ]
        : [{ branchName: "main", prefix: "" }];
      const productionDomain = new amplify.CfnDomain(this, "Domain", {
        appId: cmsApp.attrAppId,
        domainName: config.cms.domainName,
        subDomainSettings,
      });
      productionDomain.addResourceDependency(productionBranch);
      if (sharedRootDomain && stagingBranch) {
        productionDomain.addResourceDependency(stagingBranch);
      }
    }

    this.cmsAppId = cmsApp.attrAppId;
    new CfnOutput(this, "CmsAppId", { value: cmsApp.attrAppId, description: `Amplify app id for ${cmsAppName}` });
    new CfnOutput(this, "CmsOrigin", { value: productionOrigin });
    new CfnOutput(this, "CmsComputeRoleArn", {
      value: computeRole.roleArn,
      description: `SSR compute role for ${cmsAppName}; the roleArn of its Prospectus site registration`,
    });
    if (stagingEnabled) {
      new CfnOutput(this, "StagingOrigin", { value: stagingOrigin });
    }

    if (config.reader) {
      this.readerAppId = this.addReaderApp(config, config.reader);
    }

    const amplifyAppIds = [cmsApp.attrAppId, ...(this.readerAppId ? [this.readerAppId] : [])];
    this.addAuthoringRole(config, cmsApp.attrAppId, amplifyAppIds);

    if (config.autoDeploy) {
      this.addGithubDeployRole(config, [
        { appId: cmsApp.attrAppId, branch: "main" },
        ...(this.readerAppId && config.reader ? [{ appId: this.readerAppId, branch: config.reader.branchName ?? "main" }] : []),
      ]);
    }

    if (config.github) {
      this.addGithubCiRole(config, config.github, cmsApp.attrAppId, amplifyAppIds);
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

  /**
   * The merge-to-main deploy role: assumable only by a GitHub Actions run on `main` of the site's own
   * repository (OIDC, no keys), and able to do exactly one thing: start and read Amplify jobs on the
   * production branch of the site's apps.
   */
  private addGithubDeployRole(config: AmplifyAppShellSiteConfig, targets: { appId: string; branch: string }[]): void {
    const { owner, repo } = resolveGithubRepository(config);
    const provider = iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(
      this,
      "GithubDeployOidcProvider",
      this.formatArn({
        service: "iam",
        region: "",
        resource: "oidc-provider",
        resourceName: GITHUB_OIDC_PROVIDER_HOST,
        arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
      }),
    );
    const deployRole = new iam.Role(this, "GithubDeployRole", {
      roleName: `${config.siteId}-github-deploy`,
      description: `Merge-to-main deploy for ${owner}/${repo}: GitHub OIDC on refs/heads/main only; amplify:StartJob and GetJob on the production branch of the site's apps only`,
      maxSessionDuration: Duration.hours(1),
      assumedBy: new iam.OpenIdConnectPrincipal(provider, {
        StringEquals: {
          [`${GITHUB_OIDC_PROVIDER_HOST}:aud`]: "sts.amazonaws.com",
          [`${GITHUB_OIDC_PROVIDER_HOST}:sub`]: githubOidcSubjects(config, "main"),
        },
      }),
    });
    deployRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "StartAndReadProductionJobs",
        actions: ["amplify:StartJob", "amplify:GetJob"],
        resources: targets.map((target) =>
          this.formatArn({
            service: "amplify",
            resource: "apps",
            resourceName: `${target.appId}/branches/${target.branch}/jobs/*`,
            arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
          }),
        ),
      }),
    );
    new CfnOutput(this, "GithubDeployRoleArn", {
      value: deployRole.roleArn,
      description: `Role for the merge-to-main deploy workflow in ${owner}/${repo}`,
    });
  }

  private addGithubCiRole(
    config: AmplifyAppShellSiteConfig,
    github: NonNullable<AmplifyAppShellSiteConfig["github"]>,
    cmsAppId: string,
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
          [`${GITHUB_OIDC_PROVIDER_HOST}:sub`]: github.branches.flatMap((branch) => githubOidcSubjects(config, branch)),
        },
      }),
    });

    for (const statement of this.authoringStatements(config, cmsAppId, amplifyAppIds)) {
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
      ...repositoryConnectionProperties(config),
      name: readerAppName,
      description: `Papyrus static reader for ${config.siteId} (WEB)`,
      platform: "WEB",
      iamServiceRole: readerServiceRole.roleArn,
      buildSpec: readerBuildSpec(config),
      customRules: [
        ...(reader.redirects ?? []),
        { source: "/<*>", target: "/404.html", status: "404-200" },
      ],
      customHeaders: readerCustomHeaders(reader.customHeaders),
    });

    const readerBranch = new amplify.CfnBranch(this, "ReaderBranch", {
      appId: readerApp.attrAppId,
      branchName: readerBranchName,
      stage: "PRODUCTION",
      enableAutoBuild: !config.autoDeploy,
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
        subDomainSettings: (reader.domainPrefixes ?? [""]).map((prefix) => ({ branchName: readerBranchName, prefix })),
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
