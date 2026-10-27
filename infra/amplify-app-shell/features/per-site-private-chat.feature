Feature: Private newsroom chat is a per-site configuration
  Every Papyrus site can run a private newsroom chat. A site turns it on with a `chat` block in its
  site.json; the app shell and a separate chat data stack are generated from that block. Sites without
  the block get neither the chat environment on their CMS nor a chat data stack, so the chat route and
  panel stay off there. Executable by scripts/test-infra-chat.ts (isolation scenario) and infra/amplify-app-shell/lib/chat.test.ts (the rest).

  Scenario: a site with chat enabled gets the chat environment and a data stack
    Given a site config with chat enabled and the model key parameter "/papyrus/shipped/openai-api-key"
    When the app shell stack and the chat stack are synthesized
    Then the CMS production branch has PAPYRUS_PRIVATE_CHAT_ENABLED "true"
    And the production branch imports the table, bucket and queue names from the exports of "papyrus-chat-<siteId>"
    And the chat stack has two tables, one private versioned bucket, four queues and two enabled workers
    And only the run worker may read the model key parameter

  Scenario: the staging branch never gets private chat
    Given a site config with chat enabled
    When the app shell stack is synthesized
    Then the staging branch has PAPYRUS_PRIVATE_CHAT_ENABLED "false" and no chat resource names

  Scenario: a site without chat gets neither
    Given a site config without a chat block, or with chat disabled
    When the app shell stack is synthesized
    Then the production branch has PAPYRUS_PRIVATE_CHAT_ENABLED "false" and no chat resource names
    And the chat stack cannot be synthesized for it

  Scenario: the chat block cannot be contradicted by hand-set variables
    Given a site config with chat enabled and cms.environment.PAPYRUS_PRIVATE_CHAT_ENABLED
    Then validation fails naming that variable

  Scenario: chat needs a CMS and a model key parameter
    Given a site config with chat enabled but no cms section, or with no modelKeyParameter
    Then validation fails naming chat

  Scenario: two sites in one account do not share chat storage or log groups
    Given the example site configs
    Then every enabled site has its own stack name and worker log group prefix

  Scenario: the activated p.apyr.us stack is adopted without replacing anything
    Given the p-apyr-us example config names the stack PapyrusChatDataCandidate and pins the live worker code
    When the chat stack is synthesized
    Then every resource of the checked-in activated template is present with identical properties
    And the queue event source mappings are enabled as they are live
    And only the exports, descriptions and parameter defaults differ

  Scenario: editor history stays isolated per site, issuer and subject
    Given two sites with different chat tables and buckets
    Then the same issuer and subject derive different chat tenants and editors on each site
    And a different issuer or subject derives a different editor on the same site
