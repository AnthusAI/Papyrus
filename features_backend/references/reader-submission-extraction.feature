Feature: What the map pulled out of a submitted link
  A signed-in reader submits a link and it is public at once. Later, in the snapshot worker, the link is read and a model says which
  model, which maker and which task it is about; each is matched to an entity the publication already knows, and the link to a Reference
  when it has one. The result is private: only the reader who filed the submission can read it, and they confirm it or correct it on
  the Submit page. Nothing about it, and nothing about the reader, reaches a public file. A link that cannot be read is a recorded
  failure, never a failed run.

  Background:
    Given a publication whose readers rate "real" and "useful"
    And the published items "item-one" and "item-two"
    And the signed-in readers "alice" and "bob"
    And "alice" is the submitter of the first link
    And extraction is on for the publication
    And the knowledge base has the accepted model "Whisper" and the accepted maker "OpenAI"
    And the first link is a page about the model "whisper" by the maker "OpenAI" for the task "Speech recognition"

  Scenario: A submission is filed, then the worker extracts, then the reader reads and confirms
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link with the note "Worked well" titled "A small tool"
    Then "alice" is answered with status 201
    When "alice" reads the extraction of the first submission
    Then "alice" is answered with status 200
    And "alice" sees the extraction state "pending"
    When the snapshot runs
    And "alice" reads the extraction of the first submission
    Then "alice" sees the extraction state "extracted"
    And "alice" sees the model "whisper" matched to "Whisper"
    And "alice" sees the maker "OpenAI" matched to "OpenAI"
    And "alice" sees the task "Speech recognition" with no match
    And "alice" has not confirmed anything yet
    When "alice" confirms what was pulled out of the first submission
    Then "alice" is answered with status 200
    And "alice" sees her confirmation as "confirmed"
    When "alice" reads the extraction of the first submission
    Then "alice" sees her confirmation as "confirmed"

  Scenario: The reader corrects what the map got wrong
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And the snapshot runs
    And "alice" corrects the maker of the first submission to "Some Lab"
    Then "alice" sees her confirmation as "corrected"
    And her confirmation names the maker "Some Lab" with no match
    And her confirmation still names the model "whisper"

  Scenario: Another reader cannot read or confirm it
    When "alice" picks the handle "quiet-fox"
    And "bob" picks the handle "loud-owl"
    And "alice" submits the first link titled "A small tool"
    And the snapshot runs
    And "bob" reads the extraction of the first submission
    Then "bob" is answered with status 404 "unknown_submission"
    When "bob" confirms what was pulled out of the first submission
    Then "bob" is answered with status 404 "unknown_submission"
    And nobody has confirmed the first submission

  Scenario: Nothing about the extraction or the reader is in a public file
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And the snapshot runs
    And "alice" corrects the maker of the first submission to "Some Lab"
    And the snapshot runs
    Then the public files say nothing of what was pulled out
    And the public files hold no site subject, person id or email address

  Scenario: A submission held for moderation is not read until a moderator lets it through
    Given pre-moderation is on
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And the snapshot runs
    Then the link was not fetched
    When a moderator approves the first submission
    And the snapshot runs
    And "alice" reads the extraction of the first submission
    Then "alice" sees the extraction state "extracted"

  Scenario: A link that cannot be read is recorded and the reader can fill it in
    Given the first link is a dead page
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And the snapshot runs
    Then the snapshot run reports 1 failed extraction
    When "alice" reads the extraction of the first submission
    Then "alice" sees that the link could not be read: "http_4xx"
    When "alice" confirms what was pulled out of the first submission
    Then "alice" is answered with status 409 "nothing_to_confirm"
    When "alice" corrects the model of the first submission to "Whisper"
    Then "alice" sees her confirmation as "corrected"

  Scenario: Nothing can be confirmed before the link has been read
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And "alice" confirms what was pulled out of the first submission
    Then "alice" is answered with status 409 "extraction_not_ready"

  Scenario: A publication that does not turn extraction on never fetches a link
    Given extraction is off for the publication
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And the snapshot runs
    And "alice" reads the extraction of the first submission
    Then "alice" sees the extraction state "pending"
    And the link was not fetched
