Feature: A vote is recorded on the Reference, not in a Message
  Messages come only from people. A vote (accept, reject, archive or reopen) used to write a
  reference_curation Message and a comment relation. The Reference already holds the status, who set
  it, when and the note, so the rest of the vote's details now sit beside them, and a Reference keeps
  only its latest vote. The Cyclotron learns from those fields.

  Scenario: A vote records its details on the Reference and writes no Message
    Given a pending Reference in a corpus with an enabled Section
    When an agent rejects the Reference as "out_of_scope" saying "Wrong topic."
    Then the Reference update carries the status, the note and the reason code "out_of_scope"
    And the vote's actor kind on the Reference is "agent"
    And no Message and no relation were created

  Scenario: Accepting into a Section records the Section on the Reference
    Given a pending Reference in a corpus with an enabled Section
    When an agent accepts the Reference into that Section
    Then the vote's Section on the Reference is that Section
    And no Message and no relation were created

  Scenario: A later vote replaces the earlier one's details
    Given a Reference whose latest vote was a person's reject as "duplicate"
    When a person's accept without a reason is recorded on it
    Then the Reference's latest vote is an accept with no reason code

  Scenario Outline: The Cyclotron learns only from a person's vote
    Given a Reference with an accepted status and a latest vote by "<actor>"
    When its Cyclotron label is read from the vote
    Then the label is "<label>"

    Examples:
      | actor     | label   |
      | human     | include |
      | agent     | none    |
      | cyclotron | none    |
      | rule      | none    |
      | catalog   | none    |

  Scenario: A Reference nobody voted on teaches nothing
    Given a Reference with an accepted status and no recorded vote
    When its Cyclotron label is read from the vote
    Then the label is "none"

  Scenario Outline: A person's rejection teaches the negative label only for a scope reason
    Given a Reference rejected by a person with the reason "<reason>"
    When its Cyclotron label is read from the vote
    Then the label is "<label>"

    Examples:
      | reason          | label   |
      | out_of_scope    | exclude |
      | policy_exclusion | exclude |
      | duplicate       | none    |

  Scenario: The scope-training export reads the reason from the Reference
    Given a Reference rejected by a person with the reason "out_of_scope"
    When the scope-training export is built
    Then the export labels the Reference as out of scope with the reason "out_of_scope"

  Scenario: The backfill copies the latest old vote onto each Reference
    Given References with old curation Messages: a person's accept, an agent's reject and a Reference never voted on
    When the vote backfill runs as a dry run
    Then the vote backfill plans 2 References and writes nothing
    When the vote backfill runs for real
    Then the person's accept and the agent's reject are recorded on their References
    And the Reference never voted on is left alone
