Feature: The Reference lifecycle is data that agents read
  A Reference goes through named stages: collected, delivered (pending), captured and summarised, predicted, accepted or rejected, rated and grouped. The stages, who moves
  each one, whether a person is wanted by policy and what happens when nobody acts are written once, as a file in the engine that the agents load, not as rules scattered
  through the code. Every stage names its mover, which is a responsibility in the catalog or the engine, and never a person: where a person is wanted the stage says so,
  and the way to ask is a review request, not a command somebody has to run. A Reference nobody decides is not an error: it stays pending and is counted, and no stage
  removes a Reference for its age. A file that breaks one of these rules is refused with every problem named, so a lifecycle is never half valid.

  Scenario: Every stage of the Reference lifecycle names its mover
    Given the lifecycle of "Reference"
    Then its stages are "Collected, Delivered (pending), Captured and summarised, Predicted, Accepted or rejected, Rated, Grouped (same document, same story)"
    And every stage names a mover that is a responsibility in the catalog or the engine

  Scenario: A new Reference is captured, summarised and predicted without a person
    Given the lifecycle of "Reference"
    Then the stages "Collected, Delivered (pending), Captured and summarised, Predicted" ask no person
    And the "Captured" stage is moved by "Intake and capture"
    And the "Predicted" stage is moved by "Relevance and acceptance"

  Scenario: A person decides below the rung where the acceptance agent may accept
    Given the lifecycle of "Reference"
    Then the "Accepted or rejected" stage asks a person below the rung "publish_auto"

  Scenario: A five-star rating and a merge are always a person's decision
    Given the lifecycle of "Reference"
    Then the "Rated" stage is always a person's decision because "A five-star rating is always a person's decision; a machine gives three or four stars and never a five."
    And the "Grouped" stage is always a person's decision because "A merge of two Concepts or References is confirmed by a person; the knowledge run only suggests it."

  Scenario: A capture that failed is retried once and a final failure waits and is visible
    Given the lifecycle of "Reference"
    Then when nobody acts the "Captured" stage retries and then flags
    And its words say a final failure waits for a person and shows capture_failed

  Scenario: A Reference nobody decides stays pending and is counted
    Given the lifecycle of "Reference"
    Then when nobody acts the "Accepted or rejected" stage keeps the record and counts it
    And no stage removes a record for its age

  Scenario: The lifecycle reads as plain words for an agent
    Given the lifecycle of "Reference"
    When an agent asks for the lifecycle in words
    Then the words begin "Reference lifecycle."
    And the words say the "Rated" stage is moved by "Rate and curate" and "a person always decides"

  Scenario Outline: A lifecycle file that breaks a rule is refused with the reason
    Given a lifecycle file whose first stage <change>
    When the file is read
    Then it is refused saying "<reason>"

    Examples:
      | change                                      | reason                                               |
      | is moved by "an editor"                     | not a responsibility in the catalog                  |
      | is moved by "person"                        | a person is never a stage's mover                    |
      | asks a person by policy with no rung        | names the rung below which a person is asked         |
      | spikes the record when nobody acts          | no kind removes, spikes or rejects                   |
      | keeps the record without counting it        | a record that stays is counted                       |
      | is always a person's decision with no reason | says why                                             |
