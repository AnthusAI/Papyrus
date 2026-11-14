Feature: The idea standard is replayed on a site's accepted References before anyone relies on it
  Whether the standard makes ideas better is a question for the owner's eye, so a replay shows the owner what the standard would do on a site's own References.
  For the accepted References of one site that have no story yet, the single-item path runs once as a dry run: the model is asked, the draft checked and the
  point check judged, and nothing is filed, stored, marked or requested anywhere, so no flag is raised and nothing is remembered; every Reference is tried,
  whatever an earlier run rejected. The replay reports the candidates, what would be filed, what had nothing to add, which connections the ideas rested on, why
  drafts failed and what the point check said about each, and what it cost. It writes about twenty of the drafts that would be filed, each with the
  connections the newsroom had shown above it and the point check's verdict beside it, ready to be marked sentence by sentence as from the source, adding
  something or filler, followed by the drafts that were rejected and why, and every verdict with the sentences it judged. It will not start without a ceiling on
  what the model may cost, and the ceiling is held against the cost the API reports.

  Scenario: The replay writes nothing to the site and raises no flag
    Given a site with four accepted References of which two have an editor's reason
    When the replay runs with a ceiling of 5 dollars
    Then the site's backend received no write
    And no review request exists on the site

  Scenario: The standard is reported on the site's own References
    Given a site with four accepted References of which two have an editor's reason
    When the replay runs with a ceiling of 5 dollars
    Then the replay would file 2 ideas
    And the replay reports 2 References with nothing to add, resting on "acceptReason"

  Scenario: The sample shows the drafts with their connections and the point check's verdict
    Given a site with four accepted References of which two have an editor's reason
    When the replay runs with a ceiling of 5 dollars
    Then the sample has 2 drafts, with the connections shown and the point check's verdict beside each

  Scenario: A draft the point check rejects is reported with its reason
    Given the point check finds that the idea for the first of them only restates its source
    When the replay runs with a ceiling of 5 dollars
    Then the replay would file 3 ideas
    And the replay reports the point check's verdicts and the reasons drafts failed
    And the sample lists the rejected draft and why

  Scenario: The ceiling bounds the real cost
    Given a site with four accepted References of which two have an editor's reason
    When the replay runs with a ceiling of 0.0017 dollars
    Then the replay's cost is within 0.0017 dollars and it stopped for cost

  Scenario: A replay without a ceiling does not start
    Given a site with four accepted References of which two have an editor's reason
    Then a replay with no ceiling is refused
