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

  Cost accounting is opt-in. Tagging every resource updates every DynamoDB table, and a site backend with about sixty
  table stacks cannot take that in one CloudFormation operation (Papyrus 5.99.0 rolled Machines on Machines back). A site
  turns it on with site.json "costAccounting": true (default false), which sets the Amplify branch variables
  PAPYRUS_COST_TAGS=on and PAPYRUS_SITE_ID. Every scenario below that tags a site's stacks is about a site that did.

  Scenario: A site that has not opted in is deployed with no tag changes
    Given a site whose site.json does not set costAccounting
    When its app-shell stack, private chat stack and site backend are synthesized
    Then no template has an anthus: tag, no DynamoDB table has a Tags property and no function has PAPYRUS_SITE_ID or PROSPECTUS_USAGE_QUEUE_URL
    And no role may send usage to a Prospectus queue
    And the branch carries neither PAPYRUS_COST_TAGS nor PAPYRUS_SITE_ID
    And the backend synthesizes without PAPYRUS_SITE_ID

  Scenario: Only the exact value "on" turns the backend's cost accounting on
    Given PAPYRUS_SITE_ID is set but PAPYRUS_COST_TAGS is "ON", "true", "1" or empty
    Then the backend has no cost attribution

  Scenario: An untagged costed resource fails CI
    Given a stack with a table that has no anthus: tags
    When the cost tag check reads its synthesized template
    Then the check fails naming the table and the missing tags

  Scenario: A dedicated site's stacks are tagged with its site ID and account "owner"
    Given any example site with costAccounting true
    When its app-shell stack, its private chat stack and its knowledge-run stack are synthesized
    Then every costed resource carries account "owner", app "papyrus", deployment the site ID and cost key "owner/papyrus/<site>"

  Scenario: The site backend is tagged in every nested stack
    Given the app-shell stack sets PAPYRUS_COST_TAGS "on" and PAPYRUS_SITE_ID on the site's Amplify branches
    When the site backend is synthesized
    Then every costed resource in every nested stack carries cost key "owner/papyrus/<site>"
    And a costed resource CDK writes without tag support, such as the bucket auto-delete provider, is tagged too

  Scenario: A backend build that opted in without its site ID is refused
    Given an Amplify build with PAPYRUS_COST_TAGS "on" and no PAPYRUS_SITE_ID
    When the site backend is synthesized
    Then the synth fails saying the app-shell stack sets it, rather than leaving the resources untagged

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
