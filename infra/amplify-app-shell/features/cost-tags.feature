Feature: Every Papyrus stack tags its resources for Prospectus cost accounting
  Prospectus keeps a private ledger of what each customer costs Anthus and reads each day's AWS cost from Cost
  Explorer by the anthus: tags (Prospectus docs/COST_ACCOUNTING.md). Every costed resource Papyrus creates carries
  anthus:app, anthus:account and anthus:cost-key, and a dedicated site's resources also carry anthus:deployment.
  A dedicated site's resources are tagged account "owner" with the site ID as the deployment: Prospectus charges
  whichever Account holds the active papyrus-<site> entitlement, and records the cost as overhead when none does
  (Ryan, 2026-11-09). No Account ID is configured anywhere in Papyrus. Resources that serve every site are tagged
  account "shared", and Prospectus splits their cost by reported usage.
  The tags come from the Prospectus package @anthus/cost-accounting (vendored; vendor/README.md): applyCostTags in
  CDK stacks, and the same four tags written into the CloudFormation templates. These scenarios are verified by
  scripts/test-cost-tags.ts and infra/amplify-app-shell/lib/cost-tags.test.ts, which CI runs with npm test.

  A site backend is tagged in waves. CloudFormation refuses a stack operation, nested stacks included, that involves
  more than 2,500 resources, and a site backend has more (2,918 on Machines on Machines); tagging it all at once updated
  61 of 62 stacks and rolled back (Papyrus 5.99.0). The backend splits its stacks into waves of at most 1,800 resources,
  counting each stack it tags and every parent stack above them. The site's build runs papyrus-infra backend-deploy,
  which first deploys the release alone, at the wave the stack already has, then adds one wave per deploy while the
  build has time (Amplify stops a build after 30 minutes unless _BUILD_TIMEOUT says otherwise); the next build adds the
  rest. The usage senders arrive with the first wave. The site ID is the siteId of the site's own infra/site.json.
  Nothing is set by hand. Verified by scripts/test-cost-tags.ts and scripts/test-backend-deploy.mjs.

  Scenario: A build that runs ampx pipeline-deploy directly is deployed with no tag changes
    Given a site backend built without PAPYRUS_COST_TAG_WAVE
    When it is synthesized
    Then no template has an anthus: tag and no function has PAPYRUS_SITE_ID or PROSPECTUS_USAGE_QUEUE_URL
    And no role may send usage to a Prospectus queue
    And the root stack has no PapyrusCostTagWave output

  Scenario: The backend takes its site ID from the site's own site.json
    Given a site repository whose infra/site.json has siteId "dataparade"
    When backend-deploy asks for a cost tag wave
    Then the backend is tagged with deployment "dataparade" without any branch variable
    And a PAPYRUS_SITE_ID that names a different site fails the synth
    And with neither a site.json nor PAPYRUS_SITE_ID the synth fails rather than leaving the resources untagged
    And the old PAPYRUS_COST_TAGS switch does nothing

  Scenario: No wave's operation goes over CloudFormation's limit
    Given a site backend with more resources than one operation may involve
    When its stacks are planned into cost tag waves
    Then every stack is in exactly one wave and each wave costs at most 1,800 resources, counting the parent stacks it updates
    And a stack too big for the budget gets a wave of its own, and one past 2,500 cannot be planned
    And the first wave's real template change, compared with the untagged backend, is under 2,500 resources and no more than the plan counted
    And the usage senders' stacks are in the first wave, because wiring the senders changes them anyway

  Scenario: A synthesized template does not change because an unrelated file in the checkout did
    Given the site backend synthesized with no wave
    When another test, running side by side, writes a file elsewhere in the checkout
    Then the Python Lambda bundles' asset hashes are the same, because they cover only the handler and the modules they copy
    And the first wave still changes only the stacks the plan counted

  Scenario: The release is deployed alone, then the cost tags in waves
    Given a site whose backend has no cost tags yet and whose plan has 3 waves
    When its Amplify build runs papyrus-infra backend-deploy with time for every pass
    Then it deploys the release with no wave, then waves 1, 2 and 3, each one ampx pipeline-deploy
    And it stops when the root stack output PapyrusCostTagWave says "complete"

  Scenario: A wave starts only if it fits in the build
    Given a build with 20 minutes for deploying and passes that take 10 minutes each
    When papyrus-infra backend-deploy runs for a site with no cost tags and 3 waves
    Then it deploys the release and wave 1, and leaves waves 2 and 3 for the following builds
    And the next build deploys the release at wave 1, then wave 2, and the one after deploys wave 2 again, then wave 3
    And the deploy time is Amplify's build timeout (30 minutes, or _BUILD_TIMEOUT) less 10 minutes for the rest of the build

  Scenario: Once the tags are complete a deploy is one pass
    Given a site whose root stack output PapyrusCostTagWave is "complete"
    When its build runs papyrus-infra backend-deploy
    Then it runs ampx pipeline-deploy once, with every stack tagged

  Scenario: A build that failed part-way resumes without removing tags
    Given a site whose root stack output PapyrusCostTagWave is "2/4"
    When its build runs papyrus-infra backend-deploy
    Then it deploys the release at wave 2, then waves 3 and 4, never wave 1, which would take wave 2's tags off again
    And a failed pass fails the build, and the next build resumes from the wave the stack kept

  Scenario: An untagged costed resource fails CI
    Given a stack with a table that has no anthus: tags
    When the cost tag check reads its synthesized template
    Then the check fails naming the table and the missing tags

  Scenario: A dedicated site's stacks are tagged with its site ID and account "owner"
    Given any example site, whose costAccounting defaults to true
    When its app-shell stack, its private chat stack and its knowledge-run stack are synthesized
    Then every costed resource carries account "owner", app "papyrus", deployment the site ID and cost key "owner/papyrus/<site>"

  Scenario: The app shell sets no cost variables, and a site may turn its own stacks' tags off
    Given any example site
    When its app-shell stack is synthesized
    Then its production branch carries neither PAPYRUS_COST_TAGS nor PAPYRUS_SITE_ID
    And with site.json costAccounting false its app-shell and chat stacks have no anthus: tag
    And its generated production build spec deploys the backend with npx papyrus-infra backend-deploy

  Scenario: The site backend is tagged in every nested stack once every wave is deployed
    Given backend-deploy has deployed every wave for site "dataparade"
    When the site backend is synthesized
    Then every costed resource in every nested stack carries cost key "owner/papyrus/dataparade"
    And a costed resource CDK writes without tag support, such as the bucket auto-delete provider, is tagged too
    And the root stack output PapyrusCostTagWave is "complete"

  Scenario: Resources that serve every site are tagged shared
    When the monitoring, procedure runner, email submission and projection lease stacks are read
    Then every costed resource carries account "shared", app "papyrus" and cost key "shared/papyrus/"
    And the operator newsletter stack is deployed with CostAccount "shared" while each site's newsletter stack defaults to "owner"

  Scenario: Every CloudFormation template under infra/ is checked
    When the cost tag check reads every template under infra/
    Then no costed resource lacks the tags
    And Anth.us's own edge templates are left unchanged, because Anth.us is never touched without an explicit instruction

  Scenario: IAM roles carry the tags, because they authorize usage sends
    Given Prospectus lets a site's usage queue accept any role in its account tagged anthus:app "papyrus" and anthus:deployment the site ID (AnthusAI/Prospectus#150)
    When every stack and template is checked
    Then every IAM role carries the tags too, and a role without them fails CI
    And the pipeline's own deploy roles are left out, because they change only through their reviewed approval flow and never send usage

  Scenario: A model-calling function may send usage only to its own site's queue
    When the site backend is synthesized for site "dataparade"
    Then the editorial-checks and knowledge-query functions have PROSPECTUS_USAGE_QUEUE_URL set to prospectus-usage-papyrus-dataparade in the stack's own account
    And each of their roles may sqs:SendMessage on that one queue and on nothing else
    And each of their roles carries anthus:app "papyrus" and anthus:deployment "dataparade"
