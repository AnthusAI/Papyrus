Feature: A dedicated site reports what each model call used to Prospectus cost accounting
  Prospectus keeps a private ledger of what each customer costs Anthus (Prospectus docs/COST_ACCOUNTING.md). Model
  bills do not know our customers, so every Papyrus site reports the tokens it used to its own usage queue in the
  Prospectus account, and Prospectus prices them privately. A dedicated site sends as product papyrus-<site> with app
  papyrus and its site ID as the deployment. The functions that call models are AppSync resolvers the browser calls
  directly, so they never hold a verified customer Account: they report as account "owner", and Prospectus charges
  the one Account holding the active papyrus-<site> entitlement (a message with no such owner, or several, is refused
  into the dead-letter queue, with an alarm). No Account ID is configured, and a browser-supplied one is never used.
  The sender (src/papyrus_cost_usage, the Python twin of the package's TypeScript sender) tallies usage in memory
  and sends one message per Account, deployment and UTC day. It sends quantities, never dollars, and a Lambda
  flushes it before the invocation returns.

  Scenario: Two model calls on a dedicated site reach the queue once, even when the send is retried
    Given a dedicated site "dataparade"
    And its usage queue fails the first send
    When an editorial check makes two Jev classifier calls of 1200 and 800 input tokens
    And the function flushes before returning
    And the next invocation flushes again
    Then the queue holds exactly one message with operation ID unchanged from the failed send
    And the message is for app "papyrus", deployment "dataparade" and account "owner"
    And it reports 2000 "jev.tokens" and no dollar amount

  Scenario: OpenAI usage is reported as input and output tokens
    Given a dedicated site "p-apyr-us"
    When an embeddings call reports 37 prompt tokens
    And a chat call reports 500 input tokens and 120 output tokens
    And the function flushes before returning
    Then the message reports 537 "openai.tokens.input" and 120 "openai.tokens.output"

  Scenario: A site sends only to its own queue
    Given a dedicated site "pilobol-us"
    When its usage queue URL names the queue of product "papyrus-dataparade"
    Then the sender refuses to start, saying the URL must be this product's own usage queue

  Scenario: A site whose infrastructure set no usage queue records nothing
    Given a local run with no usage queue configured
    When an editorial check reports Jev classifier tokens
    Then nothing is recorded and nothing is sent

  Scenario: A backend built without a cost tag wave runs its model functions with no usage environment
    Given a site backend built without PAPYRUS_COST_TAG_WAVE, so its functions have no PAPYRUS_SITE_ID or PROSPECTUS_USAGE_QUEUE_URL
    When the editorial-checks and knowledge-query functions start and flush
    Then both start, their usage senders are inactive, and nothing is sent

  Scenario: A runtime that holds a verified Account reports that Account
    Given a dedicated site "dataparade"
    When the Next.js server, after Prospectus authorized the signed-in person for a verified Account, reports 300 "jev.tokens"
    And the function flushes before returning
    Then the message is for that verified Account

  Scenario: "owner" needs a deployment
    Given a sender with no deployment
    When usage is recorded for account "owner"
    Then it fails saying "owner" needs a deployment
