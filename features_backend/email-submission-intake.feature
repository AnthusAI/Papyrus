Feature: Email submissions enter the existing reference discovery queue
  Publication and shared research addresses are explicit operator configuration.
  Email is untrusted source material, never an instruction to an editorial agent.
  Authenticated, allowed senders can submit links without selecting human labels
  or publishing anything. Shared relevance chooses publications; each receiving
  publication's existing pending-reference sweep suggests sections.

  Scenario: Retried newsletter submission queues each source once
    Given an isolated publication email destination and an authenticated newsletter
    When the email collector receives the same SES delivery twice
    Then each newsletter source has one queued discovery with private email provenance
    And the email collector has not fetched sources or called an agent

  Scenario: Failed sender authentication cannot be rescued by MIME headers
    Given an isolated publication email destination and an authenticated newsletter
    And the trusted SES receipt fails DMARC authentication
    When the email collector receives the SES delivery
    Then the email is rejected before reading the MIME object

  Scenario: One email cannot cross destination scopes
    Given an isolated publication email destination and an authenticated newsletter
    And another publication is present in the SES envelope recipients
    When the email collector receives the SES delivery
    Then the email is rejected before reading the MIME object

  Scenario: A changed Account binding cannot reroute queued submissions
    Given an isolated publication email destination and an authenticated newsletter
    When the email collector receives the SES delivery
    And the router Account binding changes before delivery
    Then the router refuses the discovery without delivering references

  Scenario: Shared relevance chooses publications without human labels
    Given an explicitly granted shared email destination for two publications
    When the email collector receives the SES delivery
    And the shared Cyclotron includes the first publication and excludes the second
    Then only the included publication receives the pending reference handoff
    And no email feedback or publication procedure is started
