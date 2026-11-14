Feature: Email submissions enter the existing reference discovery queue
  Publication and shared research addresses are explicit operator configuration.
  Email is untrusted source material, never an instruction to an editorial agent.
  SES spam and virus verdicts remain safety gates; SPF, DKIM and DMARC are recorded
  as untrusted signals. Editors can read an inert private rendering and review links.
  No sender identity grants roles, chooses destinations, creates human labels or publishes.
  Shared relevance chooses publications; each publication's section sweep suggests sections.

  Scenario: Retried newsletter submission queues each source once
    Given an isolated publication email destination and a newsletter email
    When the email collector receives the same SES delivery twice
    Then each newsletter source has one queued discovery with private email provenance
    And the email collector has not fetched sources or called an agent

  Scenario: A newsletter larger than one work batch resumes without losing links
    Given an isolated 41-link newsletter email destination
    When the email collector processes the first batch and resumes the receipt
    Then the receipt remains processing after 25 links and finishes after 16 more
    And all 41 unique links have one durable discovery

  Scenario: Failed sender authentication is recorded for private review
    Given an isolated publication email destination and a newsletter email
    And the SES receipt reports failed SPF, DKIM and DMARC checks
    When the email collector receives the SES delivery
    Then the message is held for private review within its configured destination
    And the private receipt records untrusted authentication signals as warnings
    And the original body is available only as inert text to that publication's editors

  Scenario: An editor adds selected email links to the pending References queue
    Given an email with failed authentication is available to an editor for private review
    When the editor explicitly adds its selected article links to References
    Then each selected URL is registered or matched as a pending Reference with editor provenance
    And repeating the import is idempotent and makes no vote, classifier request, or publication

  Scenario: Authentication-warning mail cannot reach the classifier or reference router
    Given an isolated shared email destination and a newsletter email
    And the SES receipt reports failed SPF, DKIM and DMARC checks
    When the email collector receives the SES delivery
    Then the message is held for private review within its configured destination
    And no discoveries are created for the classifier or router
    And the original body is available only as inert text to that publication's editors

  Scenario: Sender headers do not grant authority or choose a destination
    Given an isolated publication email destination and a newsletter email
    And the MIME sender and SES sender headers disagree
    When the email collector receives the SES delivery
    Then the message is queued only within its configured destination
    And no Cognito editor membership lookup is made

  Scenario: Shared intake stays inside the recipient's configured publication scope
    Given a shared destination grants two publications
    When the email collector receives the SES delivery
    Then the discovery carries only the two configured destination publications
    And the Cyclotron can choose only among those publications

  Scenario: Previously rejected authentication delivery can be replayed for private review
    Given a prior authentication-rejected SES delivery with passing spam and virus checks
    When the operator replays its stored SES message
    Then the original private receipt is held for review as data-only
    And replay does not create duplicate discoveries

  Scenario: One email cannot cross destination scopes
    Given an isolated publication email destination and a newsletter email
    And another publication is present in the SES envelope recipients
    When the email collector receives the SES delivery
    Then the email is rejected before reading the MIME object

  Scenario: A changed Account binding cannot reroute queued submissions
    Given an isolated publication email destination and a newsletter email
    When the email collector receives the SES delivery
    And the router Account binding changes before delivery
    Then the router refuses the discovery without delivering references

  Scenario: Shared relevance chooses publications without human labels
    Given an explicitly granted shared email destination for two publications
    When the email collector receives the SES delivery
    And the shared Cyclotron includes the first publication and excludes the second
    Then only the included publication receives the pending reference handoff
    And no email feedback or publication procedure is started
