Feature: The minimum standard is replayed on a site's accepted References before anyone relies on it
  Whether the minimum standard makes ideas better is a question for the owner's eye, so a replay writes the same Reference both ways for the owner to read. For
  the accepted References of one site that have no story yet, the single-item path runs twice on the same References in the same order, once under the old
  standard and once under the new, as dry runs: the model is asked and the draft checked, and nothing is filed, stored, marked or requested anywhere. The replay
  reports, for each way, the candidates, what would be filed, what had nothing to add, which connections the ideas rested on, why drafts failed the check and
  what it cost. It writes about twenty pairs of the same Reference, each pair in a random order with the connections the newsroom had shown above it, and keeps
  the key to the order in a separate file so the reading stays blind. It will not start without a ceiling on what the model may cost, and the ceiling is
  held against the cost the API reports.

  Scenario: The replay writes nothing to the site and raises no flag
    Given a site with four accepted References of which two have an editor's reason
    When the replay runs with a ceiling of 5 dollars
    Then the site's backend received no write
    And no review request exists on the site

  Scenario: Both ways are reported on the same References
    Given a site with four accepted References of which two have an editor's reason
    When the replay runs with a ceiling of 5 dollars
    Then the old way would file 4 ideas and the new way 2
    And the new way reports 2 References with nothing to add, resting on "acceptReason"

  Scenario: The sample pairs the same Reference blind and the key says which was which
    Given a site with four accepted References of which two have an editor's reason
    When the replay runs with a ceiling of 5 dollars
    Then the sample has 2 pairs, each in a version A and a version B, with the connections shown and no word of which standard wrote which
    And the key names the standard behind each version

  Scenario: The ceiling bounds the real cost
    Given a site with four accepted References of which two have an editor's reason
    When the replay runs with a ceiling of 0.0017 dollars
    Then the replay's cost is within 0.0017 dollars and it stopped for cost

  Scenario: A replay without a ceiling does not start
    Given a site with four accepted References of which two have an editor's reason
    Then a replay with no ceiling is refused
