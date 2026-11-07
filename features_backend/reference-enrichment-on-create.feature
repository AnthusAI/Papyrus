@backend @reference-enrichment
Feature: A Reference created by hand is enriched before it is predicted, once, and the outcome is never a silent blank
  Ryan found ten accepted Machines on Machines References with no captured text. They had been added with the papyrus command line, and the console's Add dialog does the
  same thing: it creates a pending Reference and asks for a relevance prediction once. Nothing ever fetched the page, wrote a summary or gave the Reference its own picture,
  because the full curation stages ran only for a monitor's items and for References an editor selected from an email. Now the request that asks for the prediction also asks
  for the enrichment, as one row with one key per Reference, so a retried creation never duplicates it. The router's five minute task captures the text, writes the summary and,
  where a GROBID service is configured, the paper fields, copies the result onto the existing Reference with the same code a monitor's delivery uses, and only then decides,
  so the prediction is made on the enriched text. The automated text is labelled as not checked for completeness, a card or text that a person or an earlier correction
  supplied is never replaced, and the enrichment says which of several distinct things happened: enriched, kept, oversized, blocked, failed, or not run. A failure is written
  on the Reference with its reason and never stops the prediction or the other References. The cloud cannot read a video platform's picture or transcript, so a video is
  enriched as far as the cloud can, left in the index the local runners read, and the command that created it says how many videos need a local run. References created
  before this rule are queued by a command a person runs by hand. The monitoring table, the machine API, the capture and the model are fakes in these scenarios.

  Scenario: A Reference created through the signed-in command line or the Add dialog gets exactly one enrichment request
    Given the intake action created a pending page and a pending video
    When the intake action queues them and then queues them again
    Then each has exactly one request that asks for enrichment and the second run added none

  Scenario: A Reference created with the command line's AWS credentials gets exactly one enrichment request and a preview attempt
    Given a command that applied a plan creating one pending Reference
    When the command asks for its prediction twice and attaches previews
    Then there is one request that asks for enrichment and the preview was attempted once

  Scenario: The router enriches the existing Reference before it decides
    Given a pending page Reference whose request asks for enrichment
    When the router enriches and decides the queued requests
    Then the existing Reference has a curation card with the summary and no second Reference was created
    And the decision was made on the summary and the captured text

  Scenario: Enrichment runs once however often the request is worked
    Given a pending page Reference whose request asks for enrichment
    When the router enriches and decides the queued requests twice
    Then the page was captured once

  Scenario: A failed capture is written on the Reference and does not stop the prediction
    Given a pending page Reference whose request asks for enrichment
    When the router enriches and decides the queued requests and the page cannot be read
    Then the Reference's card says the capture failed with its reason
    And the Reference was predicted anyway and the failure was counted and logged

  Scenario: An oversized source is final, with its reason visible, and is not retried
    Given a pending page Reference whose request asks for enrichment
    When the router enriches and decides the queued requests and the source is too large
    Then the enrichment state is oversized and the reason is on the Reference
    And a later run does not fetch it again

  Scenario: Automated text is labelled and a person's text is never replaced
    Given a pending page Reference whose request asks for enrichment
    And a person had already supplied its text
    When the router enriches and decides the queued requests
    Then the page was not captured and the Reference was predicted

  Scenario: Text the cloud captured is labelled as not checked for completeness
    Given a pending page Reference whose request asks for enrichment
    When the router enriches and decides the queued requests
    Then the card says the extraction is automated and its completeness is not checked

  Scenario: A video is enriched as far as the cloud can and left for the local runners
    Given a pending video Reference whose request asks for enrichment
    When the router enriches and decides the queued requests and the video platform refuses the cloud
    Then the video is in the content-needed index the local runners read and was counted as needing a local run
    And the command line says that one video needs a local run

  Scenario: A request queued before this rule is decided as it always was
    Given a pending page Reference whose request does not ask for enrichment
    When the router enriches and decides the queued requests
    Then the page was not captured and the Reference was predicted

  Scenario: A monitor's item is enriched and delivered as before
    Given a collected monitor item
    When the router runs over the monitor item with enrichment on
    Then it was enriched and decided and no existing Reference was enriched

  Scenario: References created before this rule are queued by hand, once
    Given a corpus with an uncaptured page, a captured page and an uncaptured predicted video
    When an operator runs the enrichment backfill twice
    Then two enrich-only requests exist, none asks for a prediction, and the second run added none
