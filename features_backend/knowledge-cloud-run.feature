Feature: The scheduled cloud knowledge run
  Once a week an unattended pipeline in AWS runs the same steps an operator runs by
  hand: it exports the published items into a Biblicus corpus, models the topics with
  stable cluster identity, extracts typed entities, imports the run, lets an AI
  reviewer (GPT-6 Luna) review what the extractor proposed, writes the knowledge
  snapshot and its weekly archive, syncs the wiki and, last, projects the site.
  Each stage is one container task. It reads its inputs from the publication's state
  in S3, writes what it changed back, and records itself in a DynamoDB ledger keyed by
  publication and ISO week. Every stage can run again safely. A failure stops the
  state machine before projection, so the site stays as it was.

  Background:
    Given the cloud run for the publication "shipped" in execution "manual-1" started on 2026-10-26

  Scenario: The stages follow the runbook and projection is last
    Then the stages are, in order: corpus-sync, topic-model, typed-extraction, publish-run, ai-review, publish-relations, snapshot, archive, wiki-sync, projection

  Scenario: The corpus stage exports, indexes and extracts, and keeps the corpus in S3
    When the stage "corpus-sync" runs
    Then the stage succeeded
    And the commands include "papyrus knowledge corpus export"
    And the commands include "biblicus reindex"
    And the state in S3 holds "corpus/raw/papyrus/item-1.md"

  Scenario: Topic identity is matched against the previous run carried in S3
    Given the previous run id "prev123" is in the state
    When the stages "corpus-sync", "topic-model" run
    Then the identity command was given "--previous prev123"

  Scenario: The first run has no previous run
    When the stages "corpus-sync", "topic-model" run
    Then the identity command was not given "--previous"

  Scenario: The run is recorded for next week only after the import was applied
    Given the stages "corpus-sync", "topic-model", "typed-extraction" have run
    When the stage "publish-run" runs and the apply command fails
    Then the stage failed
    And the state in S3 has no "corpus/knowledge-run.json"
    When the stage "publish-run" runs
    Then the state in S3 records the current topic run as the previous run

  Scenario: The archive stage is called with the snapshot's options and never replaces a week
    When the stages "snapshot", "archive" run
    Then the archive command has the snapshot's options and the Monday of the week "2026-10-26"
    And no command was given "--replace"

  Scenario: A week that is already archived keeps its entry and says so in the ledger
    Given the site already holds the archive entry of the week from run "run9da9"
    When the stage "archive" runs
    Then the stage succeeded
    And no command was given "knowledge archive"
    And the ledger details for "archive" say "kept-existing (run run9da9)"

  Scenario: A corrupt archive entry fails the stage instead of being skipped or replaced
    Given the site holds a corrupt archive entry for the week
    When the stage "archive" runs
    Then the stage failed
    And no command was given "knowledge archive"
    And no command was given "--replace"

  Scenario: An archive entry for another week fails the stage
    Given the site holds an archive entry for the week that says it is for 2026-10-19
    When the stage "archive" runs
    Then the stage failed

  Scenario: A week without an entry is archived without replacing anything
    When the stage "archive" runs
    Then the stage succeeded
    And the commands include "knowledge archive"
    And no command was given "--replace"

  Scenario: Wiki pages are published without projecting
    When the stage "wiki-sync" runs
    Then the wiki publish command was given "--no-trigger"

  Scenario: Projection keeps the deletion guard on
    When the stage "projection" runs
    Then the stage succeeded
    And no command was given "--allow-deletions"

  Scenario: The site code is the commit the live site runs
    When the stage "snapshot" runs
    Then the site was fetched at the deployed commit of the Amplify app

  Scenario: The deployed commit is that of the successful deploy that ended last
    Given the Amplify jobs "60" succeeded with commit "slow" at minute 10 and "61" succeeded with commit "fast" at minute 20
    Then the deployed commit is "fast" in either order of listing

  Scenario: A checkout that is not the deployed commit stops the stage
    Given the checkout comes out at a different commit
    When the stage "snapshot" runs
    Then the stage failed
    And no command was given "knowledge snapshot"

  Scenario: Projection runs the Papyrus release the site pins
    When the stage "projection" runs
    Then the pinned release from requirements-publication.txt was installed before the project command
    And the project command ran with the pinned release first on the Python path

  Scenario: A pin without the projection lease stops the projection before it writes
    Given the pinned release lacks the projection lease
    When the stage "projection" runs
    Then the stage failed
    And no command was given "ops content project"

  Scenario: Every stage is recorded in the ledger by publication, week and execution
    When the stage "snapshot" runs
    Then the ledger says "snapshot" succeeded for "shipped" in "2026-W44"

  Scenario: A stage that already succeeded in this execution is not run again
    Given the stage "snapshot" has run
    When the stage "snapshot" runs
    Then the commands were not repeated

  Scenario: A different execution of the same week runs the stage again
    Given the stage "snapshot" has run
    When the stage "snapshot" runs in execution "scheduled-2"
    Then the stage succeeded
    And the commands include "knowledge snapshot"

  Scenario: A failed command fails the stage and the ledger keeps the reason
    Given the command "knowledge archive" fails
    When the stage "archive" runs
    Then the stage failed
    And the ledger says "archive" failed for "shipped" in "2026-W44"

  Scenario: A test execution can inject a failure into a stage
    Given the execution is "test-fail-1" and asks for a failure in "snapshot"
    When the stage "snapshot" runs
    Then the stage failed
    And no command was given "knowledge snapshot"

  Scenario: A scheduled execution ignores an injected failure
    Given the execution is "weekly-1" and asks for a failure in "snapshot"
    When the stage "snapshot" runs
    Then the stage succeeded

  Scenario: The AI reviewer accepts an entity only on evidence quoted from the item text
    Given the extractor proposed the entities "VoxCPM2" and "27B"
    And the AI reviewer accepts "VoxCPM2" quoting "OpenBMB released VoxCPM2, a 2B-parameter text-to-speech model"
    And the AI reviewer rejects "27B" as a size
    When the stage "ai-review" runs
    Then "VoxCPM2" was accepted by "ai"
    And "27B" was rejected by "ai"
    And the review log records the decisions

  Scenario: An accept with an invented quote changes nothing
    Given the extractor proposed the entities "VoxCPM2"
    And the AI reviewer accepts "VoxCPM2" quoting "VoxCPM2 is a famous model"
    When the stage "ai-review" runs
    Then nothing was accepted or rejected

  Scenario: The OpenAI key comes from an SSM SecureString parameter
    Given the extractor proposed the entities "VoxCPM2"
    When the stage "ai-review" runs
    Then the key was read from the SSM parameter "/papyrus/shipped/openai-api-key"

  Scenario: A relation is accepted only when the quote names both entities, member_of included
    Given the accepted entities "VoxCPM2" and "MiniCPM-4" and the proposed relation "member_of" between them
    And the AI reviewer accepts the relation quoting "built on the MiniCPM-4 backbone"
    When the AI reviews the relations
    Then the relation stays proposed
    Given the AI reviewer accepts the relation quoting "OpenBMB released VoxCPM2, a 2B-parameter text-to-speech model built on the MiniCPM-4 backbone"
    When the AI reviews the relations
    Then the relation is accepted by "ai"

  Scenario: A new cluster is named only when member titles are quoted
    Given a new cluster whose members are "Qwen3-TTS", "Kokoro TTS", "Chatterbox", "Voxtral TTS"
    And the AI reviewer names it "Open text-to-speech models" quoting the first three titles
    When the AI reviews the clusters
    Then the cluster is accepted as "Open text-to-speech models"

  Scenario: Projection stages use the site's plugins and refuse a different list
    Given the deployed site enables the plugins "reader-steering" only
    When the stage "projection" runs
    Then the stage failed
    And no command was given "ops content project"
    And the ledger error names "newsletter"

  Scenario: Every site-writing stage checks the plugins first
    Given the deployed site enables no plugins
    Then the stages "snapshot", "archive", "projection" each fail before running any command

  Scenario: The run only writes: it never reconciles, replaces an archived week or deletes
    When the stages "snapshot", "archive", "wiki-sync", "projection" run
    Then no command was given "--reconcile"
    And no command was given "--allow-deletions"
    And no command was given "--replace"
    And the project command passes the plugins "newsletter,reader-steering"

  Scenario: A site that sets no monitor source exports and counts its own items only
    When the stages "corpus-sync", "topic-model", "typed-extraction", "publish-run", "snapshot" run
    Then no command was given "--monitor"

  Scenario: A site that sets monitorSources exports the monitor records as data, dated for the week
    Given the site sets the monitor sources "huggingface" for 26 weeks
    When the stage "corpus-sync" runs
    Then the stage succeeded
    And the commands include "--monitor-sources huggingface --monitor-weeks 26"
    And the commands include "--as-of 2026-10-26"
    And the state in S3 holds "runs/2026-W44/monitor-records.json"

  Scenario: The import, the snapshot, the archive and the wiki read the same records file
    Given the site sets the monitor sources "huggingface" for 26 weeks
    And the stages "corpus-sync", "topic-model", "typed-extraction" have run
    When the stages "publish-run", "snapshot", "archive", "wiki-sync" run
    Then each of the commands "knowledge publish-run", "knowledge snapshot", "knowledge archive", "knowledge wiki sync" was given "--monitor-records" with the week's records file

  Scenario: Only the import is given the ledger of what it wrote before, kept with the corpus so it outlives the week
    Given the site sets the monitor sources "huggingface" for 26 weeks
    And the stages "corpus-sync", "topic-model" have run
    When the stages "typed-extraction", "publish-run", "snapshot" run
    Then the command "knowledge publish-run" was given "--monitor-ledger" with the corpus's import ledger
    And no command "knowledge snapshot" was given "--monitor-ledger"
