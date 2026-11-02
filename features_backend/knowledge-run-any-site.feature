Feature: Any Papyrus site can run the knowledge run from configuration alone
  The daily knowledge run began as Shipped's, and it assumed what Shipped had: a corpus named like the site, a hand-written vocabulary
  of entity kinds, a Knowledge Map in the site repository and a seeded configuration folder in its run state. A new site has none of
  that and should not need it. It needs its published items and the References its monitors route to it; the run then models the
  topics, extracts entities with a generic vocabulary (organization, product, person, topic), counts the routed records, writes the
  snapshot and hands the trend and monitor story steps what they need to draft cited stories for an editor to judge. Each assumption
  has a default, and a site that does supply its own vocabulary, map or corpus key gets exactly what it supplied. A site with nothing
  yet to model, no items and no records, still has a successful run: every stage says there is nothing to do, and what the run cost is
  still recorded. Shipped, whose configuration is all in place, runs the commands it has always run.

  Scenario: A site whose References live in a corpus of another name is read from that corpus
    Given a site "p-apyr-us" whose References live in the knowledge corpus "ai-ml-research", with monitor sources "routed"
    When the whole run goes through all its stages
    Then every command that names the corpus names "ai-ml-research" and none names "p-apyr-us"
    And the run state, the ledger and the actor stay keyed by "p-apyr-us"

  Scenario: A site that names no corpus key uses its own id, as before
    Given a site "shipped" with monitor sources "routed"
    When the whole run goes through all its stages
    Then every command that names the corpus names "shipped"

  Scenario: A new site with no vocabulary is given the generic one and keeps it in its state
    Given a new site "newsite" with published items and no configuration in its run state
    When the stages "corpus-sync", "topic-model", "typed-extraction" run
    Then the ledger says "typed-extraction" succeeded for "newsite" in "2026-W44"
    And the typed extraction was given a vocabulary with the kinds "organization", "product", "person" and "topic"
    And the state in S3 holds "config/vocabulary.yml"

  Scenario: The generic vocabulary is valid YAML for the entity extractor
    Given a new site "newsite" with published items and no configuration in its run state
    When the stages "corpus-sync", "topic-model", "typed-extraction" run
    Then every entity kind in the vocabulary has only a key and one label, so the extractor accepts it

  Scenario: A vocabulary an editor wrote is never replaced by the default
    Given a site "shipped" whose editors wrote their own vocabulary
    When the stages "corpus-sync", "typed-extraction" run
    Then the typed extraction was given a vocabulary with the kind "maker"
    And the typed extraction was not given a vocabulary with the kind "organization"

  Scenario: A new site needs no Knowledge Map, concept kinds or scoring file to get a snapshot
    Given a new site "newsite" with published items and no configuration in its run state
    When the whole run goes through all its stages
    Then the run succeeded
    And the snapshot, archive and wiki commands were given no beats config and no concept kinds
    And a snapshot was written and the site was projected

  Scenario: A map file the site names but does not have is left out instead of failing the run
    Given a new site "newsite" with published items and no configuration in its run state
    And the site names the beats config "web/not-there.json"
    When the stage "snapshot" runs
    Then the stage succeeded
    And the snapshot command was given no beats config

  Scenario: A new site's GraphQL endpoint is the address AppSync reports for its API when the state has none
    Given a new site "newsite" with published items and no configuration in its run state
    When the stage "corpus-sync" runs
    Then the state in S3 holds "config/amplify_outputs.json"
    And the backend endpoint of the commands is the address AppSync reports for the API

  Scenario: A site with no items and no monitor records succeeds every stage with nothing to do
    Given a new site "newsite" with no published items and no monitor records
    When the whole run goes through all its stages
    Then the run succeeded
    And every stage's ledger row says "nothing to do"
    And no command modelled, extracted, imported, snapshotted or projected anything

  Scenario: An empty run still records what it cost
    Given a new site "newsite" with no published items and no monitor records
    When the whole run goes through all its stages
    Then every stage's ledger row has a cost
    And the run's total cost is recorded

  Scenario: A site whose first item arrives is modelled in the next run
    Given a new site "newsite" with no published items and no monitor records
    And the stages "corpus-sync" have run
    When an item is published and the stage "corpus-sync" runs in execution "manual-2"
    Then the run state says the site has 1 document
    And the commands include "biblicus extract build"

  Scenario: A site that has monitor records but no items counts the records and models no topics
    Given a new site "newsite" with no published items and 2 monitor records from "routed"
    When the whole run goes through all its stages
    Then the run succeeded
    And the records are imported without clusters or extracted entities
    And no topic model or typed extraction ran
    And a snapshot was written and the site was projected
