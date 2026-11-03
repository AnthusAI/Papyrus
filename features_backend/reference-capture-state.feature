@backend @reference-capture-state
Feature: Every Reference records how much of its content the newsroom holds, so people can capture what we could not
  Some accepted References have only a title and an address, because the page was behind an I'm-not-a-robot gate or a paywall. A person can
  fix that by uploading a PDF or pasting the text, and it is worth their effort for the highest-rated ones. To list them, each Reference
  carries a capture state: "full" when the newsroom holds the content, "thin" when it holds only a teaser or text that looks cut off, "none"
  when it holds nothing, and "running" while a capture is in progress. An empty state means "none": a Reference a monitor discovered has only
  its address. Only "full" counts as captured. The rule is the same everywhere. Text of fewer than 250 words is thin, and so is text that ends
  with a subscribe phrase or seems to stop short. An editor's word beats the signals: "complete" counts as full, "incomplete" or "incorrect"
  counts as thin so it asks for a person again, and text a person pasted or uploaded is full. No capture classifier exists yet; this rule decides
  today. Nothing here touches production: the backend is in memory.

  Scenario: A Reference nobody has tried to capture has no capture state and nothing is written
    Given a site with a pending Reference whose source is a news article
    Then the Reference has no capture state

  Scenario: A long article captured by the curation run is full
    Given a site with a pending Reference whose source is a news article of 300 words
    When the curation procedure runs for the Reference
    Then the Reference's capture state is "full"

  Scenario: A short article is a teaser, so it is thin and still needs a person
    Given a site with a pending Reference whose source is a news article
    When the curation procedure runs for the Reference
    Then the Reference's capture state is "thin"

  Scenario: A source that refuses the request leaves the Reference with no capture state
    Given a site with a pending Reference whose source is a news article
    And the source refuses the request as "blocked"
    When the curation procedure runs for the Reference
    Then the Reference has no capture state

  Scenario: A capture still in progress with no text yet is running
    Given a site with a pending Reference whose source is a news article
    When the curation procedure has started and not finished
    Then the Reference's capture state is "running"

  Scenario: A running recapture of a Reference that has text keeps its state
    Given a site with a pending Reference whose source is a news article of 300 words
    And the curation procedure has run for the Reference
    When the curation procedure has started and not finished
    Then the Reference's capture state is "full"

  Scenario: An editor pastes the text of a blocked Reference and it becomes full
    Given a site with a pending Reference whose source is a news article
    And the source refuses the request as "blocked"
    And the curation procedure has run for the Reference
    When the editor "editor-one" pastes the full text "A short pasted article of a few words." and labels the capture "incomplete"
    Then the Reference's capture state is "full"

  Scenario: An editor pastes the text of a Reference nobody ever tried to capture and it becomes full
    Given a site with a pending Reference whose source is a news article
    When the editor "editor-one" pastes the full text "A short pasted article of a few words." and labels the capture "incomplete"
    Then the Reference's capture state is "full"

  Scenario: An editor uploads a PDF of a blocked Reference and it becomes full
    Given a site with a pending Reference whose source is a news article
    And the source refuses the request as "blocked"
    And the curation procedure has run for the Reference
    When the editor "editor-one" uploads a PDF of a research paper and labels the capture "incomplete"
    Then the Reference's capture state is "full"

  Scenario: An editor who says the capture was incomplete makes a long text ask for a person again
    Given a site with a pending Reference whose source is a news article of 300 words
    And the curation procedure has run for the Reference
    When the editor labels the capture "incomplete" without giving text
    Then the Reference's capture state is "thin"

  Scenario: An editor who says a short capture was complete makes it full
    Given a site with a pending Reference whose source is a news article
    And the curation procedure has run for the Reference
    When the editor labels the capture "complete" without giving text
    Then the Reference's capture state is "full"

  Scenario: A capture that ends with a subscribe phrase is doubted, so it is thin until an editor vouches for it
    Given a site with a pending Reference whose source is a news article of 300 words ending with "Subscribe to continue reading."
    When the curation procedure runs for the Reference
    Then the Reference's capture state is "thin"
    When the editor labels the capture "complete" without giving text
    Then the Reference's capture state is "full"

  Scenario: Older captured text attached to a Reference counts the same way
    Given a site with a pending Reference whose source is a news article
    When extracted text of 12000 characters is attached to the Reference
    Then the Reference's capture state is "full"
    When extracted text of 600 characters is attached to another Reference
    Then that Reference's capture state is "thin"

  Scenario: A new version of a Reference keeps the capture state of the version it replaces
    Given a site with a pending Reference whose source is a news article of 300 words
    And the curation procedure has run for the Reference
    When a new version of the Reference is imported
    Then the new version's capture state is "full"

  Scenario: The backfill sets the state from the attachments, counts it, and a second run writes nothing
    Given a corpus with a captured Reference, a thin Reference, a Reference with no capture and a Reference with a stale capture state
    When the capture state backfill runs for that corpus
    Then the backfill reports 3 capture states changed
    And the captured Reference is "full", the thin one "thin", and the stale one has no state
    And the Reference with no capture was not written
    When the capture state backfill runs for that corpus again
    Then the backfill reports 0 capture states changed

  Scenario: A dry run of the backfill counts and writes nothing
    Given a corpus with a captured Reference, a thin Reference, a Reference with no capture and a Reference with a stale capture state
    When the capture state backfill runs for that corpus as a dry run
    Then the backfill reports 3 capture states changed
    And nothing was written to any Reference

  Scenario: Search can narrow to captured or not captured References
    Given searchable References where two are full, one is thin, one is running and one has no capture state
    When an editor searches with Captured "yes"
    Then the results are the two full References
    When an editor searches with Captured "no"
    Then the results are the thin, running and empty References
    And a search cursor made with Captured "no" is refused for Captured "yes"

  Scenario: Reviewed Accepted in a search never lists a rejected Reference
    Given searchable References where one is accepted and not captured, one is accepted and captured, one is rejected and not captured, and one is pending
    When an editor searches with Reviewed "accepted" and Captured "any"
    Then the results are both accepted References and no rejected one
    When an editor searches with Reviewed "accepted" and Captured "no"
    Then the results are only the accepted Reference that is not captured
    And a search cursor made with Reviewed "accepted" is refused for Reviewed "rated"
