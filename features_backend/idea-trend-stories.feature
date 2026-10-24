Feature: The idea pipeline drafts trend stories from the weekly knowledge snapshot
  Every week a site's knowledge run publishes a snapshot: which clusters and entities are rising, with their weekly item counts, and
  an archive of earlier weeks. The trend-story path turns that snapshot into story drafts. The signals (the rising clusters and
  entities) are picked without a model. One call to the repository's default model (GPT-6 Luna) writes each draft as single
  sentences, each naming the signals it rests on. A deterministic citation check then decides which drafts may be filed: every
  sentence must cite a signal that exists in the snapshot, and every number or date in it must appear in the signals it cites. A draft
  that fails is not filed and the run record says which sentence failed and why. A draft that passes is filed as a story draft
  Proposal in the draft state, proposed by AI, with the cited clusters and entities as its targets and a small chart spec of their
  weekly counts stored with it, so an editor approves the copy and the figure together. Nothing is approved, moved or published by the
  run. One soft review request covers the whole run. A dry run shows the drafts and the check without filing anything.

  Background:
    Given a weekly knowledge snapshot for the week of "2026-10-19" with two named clusters and four entities
    And the site has the sections "Analysis" and "News"

  Scenario: The signals are the rising clusters and entities, chosen without a model
    When the operator reads the signals of the snapshot
    Then the signals are the two clusters, then the three trending entities, then the one new entity
    And each signal names its weekly counts for the 8 weeks ending 2026-10-19

  Scenario: A draft whose sentences all cite signals in the snapshot is filed as a draft story Proposal proposed by AI
    When the model drafts a trend story citing Hugging Face and Apache-2.0
    And the operator drafts trend stories and files them as Proposals
    Then 1 trend draft is filed as a "story_draft" Proposal
    And the draft is proposed by AI and still in the draft state
    And the Proposal targets the entities "platform--hugging-face" and "licence--apache-2-0"
    And every sentence of the draft is recorded with the signals it rests on
    And the model asked for was "gpt-6-luna"

  Scenario: The Proposal carries a chart spec drawn from the cited signal's weekly counts
    When the model drafts a trend story citing Hugging Face and Apache-2.0
    And the operator drafts trend stories and files them as Proposals
    Then the Proposal evidence holds a line chart of Hugging Face with the counts 1, 2, 3, 4, 7, 3, 3, 2
    And the chart's weeks run from 2026-08-31 to 2026-10-19
    And the body lists the signals cited under the sentences that cite them

  Scenario: A sentence with no citation blocks the draft
    When the model drafts a trend story with a body sentence that cites nothing
    And the operator drafts trend stories and files them as Proposals
    Then 0 trend drafts are filed
    And the run record says that sentence failed with "no_citation"

  Scenario: A citation of a signal that is not in the snapshot blocks the draft
    When the model drafts a trend story with a body sentence citing a signal that does not exist
    And the operator drafts trend stories and files them as Proposals
    Then 0 trend drafts are filed
    And the run record says that sentence failed with "unknown_signal:S99"

  Scenario: A number the cited signals do not hold blocks the draft
    When the model drafts a trend story stating 40 items for Hugging Face
    And the operator drafts trend stories and files them as Proposals
    Then 0 trend drafts are filed
    And the run record says that sentence failed with "number_not_in_cited_signals:40"

  Scenario: A draft that rests on one signal with two body sentences fails, and the run record keeps its text
    When the model drafts a trend story with two body sentences that cite one signal
    And the operator drafts trend stories and files them as Proposals
    Then 0 trend drafts are filed
    And the run record says that sentence failed with "fewer_than_three_body_sentences"
    And the run record says that sentence failed with "fewer_than_two_signals_cited"
    And the failed draft in the run record keeps its headline, dek, body and citations

  Scenario: The run never approves, moves or publishes anything
    When the model drafts a trend story citing Hugging Face and Apache-2.0
    And the operator drafts trend stories and files them as Proposals
    Then no Proposal is moved out of the draft state
    And no request to publish Proposals is made

  Scenario: One soft review covers the run
    When the model drafts a trend story citing Hugging Face and Apache-2.0
    And the operator drafts trend stories and files them as Proposals with review requests
    Then one soft review "1 new trend story draft to review" is open for the run's batch
    And the review links the filed Proposal

  Scenario: A dry run shows the drafts and the check and files nothing
    When the model drafts a trend story citing Hugging Face and Apache-2.0
    And the model drafts a trend story with a body sentence that cites nothing
    And the operator dry-runs the trend drafts
    Then the dry run lists 1 draft that passed and 1 that failed the citation check
    And no Proposal is filed, no file is stored and no review is raised

  Scenario: A story draft Proposal with the same targets is not filed again
    Given an editor can read an earlier story draft Proposal with the same targets
    When the model drafts a trend story citing Hugging Face and Apache-2.0
    And the operator drafts trend stories and files them as Proposals
    Then 0 trend drafts are filed
    And the run record says the draft has the same targets as the earlier Proposal

  Scenario: An operator role files drafts under IAM and the run says dedupe against Proposals was skipped
    Given the operator signs in with IAM and cannot read Proposals
    When the model drafts a trend story citing Hugging Face and Apache-2.0
    And the operator drafts trend stories and files them as Proposals
    Then 1 trend draft is filed as a "story_draft" Proposal
    And the run record says earlier Proposals could not be read with IAM

  Scenario: The archive of the previous week adds a signal fact for each cluster
    Given the site publishes its snapshot as files with an archived earlier week in which "Decision models" held 17 items
    When the operator reads the signals of the snapshot
    Then the cluster "Decision models" carries the 17 items of the earlier archived week
