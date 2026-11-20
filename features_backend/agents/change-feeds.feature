Feature: A change to a Reference, review request, Message, translation request or Delivery wakes the agents that listen for it, once
  The Item change feed turns a change to a Story into one wake for each agent that listens. The other tables agents react to work the same way,
  with the same normalized change (the table, the kind, the record, its lineage and version, what changed,
  who changed it and when), the same listener index and the same wake on the site's queue. A Reference is created, accepted, rated or captured again. A review
  request is answered, and the answer is for the agent that asked. A Message is posted, and the wake is for the listeners of the Story, Reference or Delivery the
  comment is on. A translation is wanted. A Delivery changes state. Whoever wrote the change (a person in the console, the command line, an agent) the stream
  record is the same, so no writer has to call anything. The feed finds the agents in the site's listener index, one small document read by its live version,
  and never lists the Automation table or any other table; the one lookup it makes is the thread of a posted Message, by id, and only when some agent listens
  for a posted Message. A change nobody listens for sends nothing. An agent's own change never wakes that agent. The same stream record delivered twice makes
  the same wake keys, so it starts nothing twice. Where a table already has two stream readers the feed is not a third: the reader that stays on the stream
  passes the batch to the feed, which cannot tell the difference.

  Background:
    Given the site "sample" with its wake queue and its listener index
    And these agents listen for changes
      | agent          | procedure           | paid  | kind                | change      | filter                             |
      | curate         | references.curate   | false | Reference           | created     |                                    |
      | rate           | references.rate     | false | Reference           | accepted    |                                    |
      | announce       | announce.decide     | true  | Reference           | accepted    |                                    |
      | star-watch     | references.stars    | false | Reference           | rated       | stars=5                            |
      | recheck        | references.recheck  | false | Reference           | recaptured  |                                    |
      | copy-edit      | story.copy_edit     | true  | ReviewRequest       | answered    |                                    |
      | other-reviewer | story.other         | false | ReviewRequest       | answered    |                                    |
      | fact-check     | story.fact_check    | true  | Message             | posted      | subjectKind=Story,actorKind=person |
      | story-notes    | story.notes         | false | Message             | posted      | subjectKind=Story                  |
      | reference-talk | references.talk     | false | Message             | posted      | subjectKind=Reference              |
      | translate      | story.translate     | true  | LocalizationRequest | wanted      | language=zh                        |
      | learn          | announce.learn      | false | Delivery            | state_changed | state=sent                       |
    And the Story "story-1" has the comment thread "thread-story" and the Reference "ref-1" has the comment thread "thread-reference"

  Scenario: Accepting a Reference wakes the agents that listen for it
    When a person accepts the Reference "ref-1"
    Then the queue holds 2 wakes, for the agents "announce" and "rate"
    And the wake key for "rate" is "rate|ref-1|ref-1-v1|accepted"
    And the wake for "rate" names the person "ada" and when they accepted it
    And the wake for "announce" says the step is paid
    And the wake for "rate" says the table is "Reference" and the change is "accepted"
    And the wake for "rate" is in the message group of "rate" and "ref-1"

  Scenario: A new Reference wakes only the agents that listen for new ones
    When a person adds the Reference "ref-1"
    Then the queue holds 1 wake, for the agent "curate"

  Scenario: A star rating wakes an agent whose filter matches it
    When a person gives the Reference "ref-1" 5 stars
    Then the queue holds 1 wake, for the agent "star-watch"
    And the wake key is "star-watch|ref-1|ref-1-v1|rated.5"

  Scenario: A star rating nobody asked for sends nothing
    When a person gives the Reference "ref-1" 3 stars
    Then the queue holds 0 wakes

  Scenario: Capturing a Reference again wakes the agent that listens for it
    When the Reference "ref-1" is captured again
    Then the queue holds 1 wake, for the agent "recheck"

  Scenario: A Reference's first capture is not a capture again
    When the Reference "ref-1" is captured for the first time
    Then the queue holds 0 wakes

  Scenario: Answering a review request wakes the agent that asked
    When a person answers the review request "rr-1" that "copy-edit" raised about the Story "story-1"
    Then the queue holds 1 wake, for the agent "copy-edit"
    And the wake key is "copy-edit|story-1|rr-1|answered"
    And the wake for "copy-edit" names the person "ada" and when they answered

  Scenario: An answer is not a wake for an agent that did not ask
    When a person answers the review request "rr-1" that "copy-edit" raised about the Story "story-1"
    Then no wake is for the agent "other-reviewer"

  Scenario: An answer to a request an agent that does not listen raised sends nothing
    When a person answers the review request "rr-2" that "publish-gate" raised about the Story "story-1"
    Then the queue holds 0 wakes

  Scenario: A request that is not yet answered is no change
    When a person edits the open review request "rr-1" that "copy-edit" raised about the Story "story-1"
    Then the queue holds 0 wakes

  Scenario: A person's Message on a Story wakes the Story's agents
    When a person comments on the Story "story-1"
    Then the queue holds 2 wakes, for the agents "fact-check" and "story-notes"
    And the wake key for "fact-check" is "fact-check|story-1|message-1|posted"
    And the wake for "fact-check" says the subject is the Story "story-1"
    And the comment thread was read once

  Scenario: A Message on a Reference wakes the Reference's agents and not the Story's
    When a person comments on the Reference "ref-1"
    Then the queue holds 1 wake, for the agent "reference-talk"

  Scenario: An agent's own write does not wake itself for the same version
    When the agent "story-notes" comments on the Story "story-1"
    Then the queue holds 0 wakes
    And no wake is for the agent "story-notes"

  Scenario: An agent's comment wakes the other agents that listen for it
    When the agent "fact-check" comments on the Story "story-1"
    Then the queue holds 1 wake, for the agent "story-notes"
    And the wake for "story-notes" says the change was made by an agent

  Scenario: An agent's own acceptance does not wake that agent
    When the agent "rate" accepts the Reference "ref-1"
    Then the queue holds 1 wake, for the agent "announce"

  Scenario: A translation that is wanted wakes the agent for its language
    When a person asks for the translation of the Story "story-1" into "zh"
    Then the queue holds 1 wake, for the agent "translate"
    And the wake key is "translate|story-1|story-1-v4|wanted.zh.2026-11-18T09:00:00Z"

  Scenario: A translation in a language nobody listens for sends nothing
    When a person asks for the translation of the Story "story-1" into "fr"
    Then the queue holds 0 wakes

  Scenario: Asking again for the same translation is a new wake
    When a person asks for the translation of the Story "story-1" into "zh"
    And a person asks for the translation of the Story "story-1" into "zh" again later
    Then the queue holds 2 wakes, for the agents "translate" and "translate"

  Scenario: A Delivery changing state wakes the agent that listens for that state
    When the Delivery "delivery-1" is sent
    Then the queue holds 1 wake, for the agent "learn"
    And the wake key is "learn|delivery-1|3|state_changed.sent"

  Scenario: A Delivery drafted or only refreshed sends nothing
    When the Delivery "delivery-1" is drafted
    And the table refreshes the counts of the Delivery "delivery-1"
    Then the queue holds 0 wakes

  Scenario: A change nobody listens for sends nothing, and nothing is looked up
    When a person edits the title of the Reference "ref-1"
    And a person edits a comment
    And a person posts a console chat turn
    And the table removes the Reference "ref-1"
    Then the queue holds 0 wakes
    And the comment thread was not read

  Scenario: The thread of a Message is read only when an agent listens for posted Messages
    Given the deploy writes the listener index without any agent that listens for a posted Message
    When a person comments on the Story "story-1"
    Then the queue holds 0 wakes
    And the comment thread was not read

  Scenario: A change never lists the Automation table or any table
    When a person accepts the Reference "ref-1"
    And a person comments on the Story "story-1"
    And a person answers the review request "rr-1" that "copy-edit" raised about the Story "story-1"
    Then the queue holds 5 wakes
    And no table was listed or scanned
    And the change feeds' code has no list of any table

  Scenario: A redelivered stream record starts nothing twice
    When a person accepts the Reference "ref-1"
    And the same change record is delivered again after the queue's window
    Then the queue holds 4 wakes
    And the wakes carry 2 different wake keys

  Scenario: A row of another tenant is nobody's wake
    When a person accepts a Reference that belongs to the tenant "beta"
    Then the queue holds 0 wakes
    And the listener index was not read

  Scenario: A wake that cannot be sent fails its record, and the retry sends only what is missing
    Given the queue refuses the second wake it is given
    When a person accepts the Reference "ref-1"
    Then the batch reports the record as failed
    When the queue accepts wakes again and the change batch is retried
    Then the queue holds 2 wakes, for the agents "announce" and "rate"

  Scenario: A record from a stream the feed was not given is refused, never guessed
    When a record arrives from a stream the feed does not read
    Then the feed refuses the batch and names the stream

  Scenario: Where a table already has two readers, the reader that stays on the stream passes the batch to the feed
    Given the Reference stream has two other readers and the word index relays its batches to the feed
    When a person accepts the Reference "ref-1"
    Then the queue holds 2 wakes, for the agents "announce" and "rate"
    And the relayed batch reached the feed once

  Scenario: A relayed record the feed cannot finish is reported to the reader, which reports it
    Given the Reference stream has two other readers and the word index relays its batches to the feed
    And the queue refuses the second wake it is given
    When a person accepts the Reference "ref-1"
    Then the reader reports the record as failed

  Scenario: The deploy writes the listener index with the new changes
    Given the definitions "rate" and "copy-edit" in Git for changes of other tables
    When the deploy writes the listener index for these definitions
    Then the site's listener index lists "rate" under Reference/accepted and "copy-edit" under ReviewRequest/answered
