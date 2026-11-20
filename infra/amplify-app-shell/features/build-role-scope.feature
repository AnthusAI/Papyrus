Feature: A site's Amplify build can run with a scoped role instead of account administrator
  Every site's production build has run as the AWS-managed AdministratorAccess policy, so one bad merge, a bad install script or a buggy
  deploy command could rewrite the pipeline's own roles or touch another site's data. The site setting cms.buildRole chooses what the
  build runs as: administrator (the default, so nothing changes until a site opts in) or scoped, which is AWS's AmplifyBackendDeployFullAccess,
  the grants this site's build commands use, and an explicit deny on the pipeline's own roles and stacks. A site moves to scoped one at a time,
  starting with Machines on Machines, and moves back by changing one value. Scoping does not narrow the account's CDK bootstrap execution role,
  which still decides what a deployed template may create.
  Executable by scripts/test-infra-build-role.ts.

  Scenario: A site that does not set cms.buildRole keeps the administrator build role
    Given a site config that does not set cms.buildRole
    When the app shell template is synthesized
    Then the build role carries AdministratorAccess and says so in its description
    And no scoped grants policy is created

  Scenario: A scoped build role carries no administrator policy anywhere
    Given a site config with cms.buildRole "scoped"
    When the app shell template is synthesized
    Then the build role carries AmplifyBackendDeployFullAccess
    And no template resource names AdministratorAccess, PowerUserAccess or IAMFullAccess

  Scenario: The scoped role is granted what this site's build commands use
    Given a site config with cms.buildRole "scoped"
    When the app shell template is synthesized
    Then the build role may read this site's parameters under /papyrus/<site>/
    And it may reach this site's wake queue, schedule group and scheduler role, passing the role only to the scheduler
    And it may sign this site's authoring requests and read and write its media and preview files
    And none of its allowed statements grants a wildcard over IAM or STS

  Scenario: The scoped role can never change the pipeline's own roles or stacks
    Given a site config with cms.buildRole "scoped"
    When the app shell template is synthesized
    Then the build role is denied every IAM action and assuming roles named papyrus-pipeline-, papyrus-stack- and papyrus-shared-
    And it is denied every CloudFormation action on the papyrus-stack-pipeline and papyrus-pipeline-approver stacks

  Scenario: A value other than administrator or scoped is refused
    Given a site config with cms.buildRole "admin"
    When the site config is validated
    Then validation fails naming cms.buildRole and the two allowed values

  Scenario: Choosing scoped changes only the build role and its grants
    Given the same site config with and without cms.buildRole "scoped"
    When both templates are synthesized
    Then every resource other than the build role and its grants policy is the same
