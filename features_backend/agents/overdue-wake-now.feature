Feature: Wake now on an Overdue Delivery or review deadline sends its timer's wake again, once, with the same key
  A Delivery and a soft review's deadline are woken by the engine's follow-up timers, not by an adopted agent, so waking an agent now cannot reach them. When
  one is Overdue (its timer's wake was lost, so nothing ran), an editor presses Wake now beside it on Today, or runs `papyrus agents wake-overdue`: one row of
  the operation table, `agents_wake_overdue`, for editors and admins who are people. It is the hygiene check's recovery for that one record: the record is
  read by its id and must be Overdue, and the wake its own timer sends goes on the site's wake queue again with the same key. The queue drops a repeat inside
  its window and the runner answers a repeat after it as a duplicate, so the work is done once. The wake says who sent it again and why, and so does the run
  it starts. A record that is not Overdue is refused, and nothing is sent.

  Background:
    Given a site whose clock reads "2026-11-19T12:00:00Z"
    And the site's follow-up timers, named as the site's functions name them

  Scenario: Wake now on an Overdue Delivery sends its timer's wake once, with the same key
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    When Edie presses Wake now on the Delivery "weekly" on Today because "The weekly email did not go out"
    Then one wake went on the site's queue for the Delivery "weekly"
    And it has the wake key the Delivery's own timer used, and the timer's request
    And the wake says Edie sent it again because "The weekly email did not go out"
    And Wake now answers in words that it was woken now by "edie@example.test" with the same key

  Scenario: Pressing Wake now twice inside the queue's window puts one wake on the queue
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    When Edie presses Wake now on the Delivery "weekly" on Today because "The weekly email did not go out"
    And Edie presses Wake now on the Delivery "weekly" on Today because "Still nothing"
    Then the site's queue holds one wake for it

  Scenario: The woken Delivery runs once, and its run says who woke it and why
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    When Edie presses Wake now on the Delivery "weekly" on Today because "The weekly email did not go out"
    And the runner takes the re-sent wake
    And once the queue has forgotten the first message, Edie presses Wake now on the Delivery "weekly" on Today because "Once more"
    And the runner takes the re-sent wake
    Then the site has exactly one run record for the Delivery "weekly"
    And the second answer says duplicate
    And the run record's summary says it was woken by "edie@example.test" because "The weekly email did not go out"

  Scenario: Wake now on an Overdue review deadline sends its deadline wake with the same key, and the request goes on without review
    Given the procedure "ideas" raised a soft review with the deadline "2026-11-19T09:00:00Z" whose deadline wake was lost
    When Edie presses Wake now on the review request on Today because "The draft has waited long enough"
    Then it has the wake key the review request's own deadline timer used
    And the wake says Edie sent it again because "The draft has waited long enough"
    And running that wake times the review request out with the note "proceeded without review"

  Scenario: A Delivery whose wake is still in flight is not Overdue, so Wake now sends nothing
    Given the Delivery "daily" waits for its release at "2026-11-19T11:45:00Z" and its timer has fired
    When Edie presses Wake now on the Delivery "daily" on Today because "Impatient"
    Then Wake now is refused as "constraint_conflict", saying "Delivery daily is not Overdue"
    And Wake now put nothing on the site's queue

  Scenario: A Delivery that waits for nothing has no timer wake to send
    Given the Delivery "sent" waits for nothing
    When Edie presses Wake now on the Delivery "sent" on Today because "Again"
    Then Wake now is refused as "constraint_conflict", saying "waits for nothing"
    And Wake now put nothing on the site's queue

  Scenario: A record that is not on the site is not found
    When Edie presses Wake now on the Delivery "nowhere" on Today because "Try it"
    Then Wake now is refused as "not_found", saying "There is no Delivery nowhere"
    And Wake now put nothing on the site's queue

  Scenario: Only an editor or admin who is a person wakes a record now
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    When Rita, a reader, presses Wake now on the Delivery "weekly" because "I can see it"
    Then Wake now is refused as "not_authorized", saying "Only an editor or an admin"
    When an agent asks the command line to wake the Delivery "weekly" now because "I am stuck"
    Then Wake now is refused as "human_required", saying "needs a person"
    And Wake now put nothing on the site's queue

  Scenario Outline: Wake now works the same on Today and on the command line
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    When Edie presses Wake now on the Delivery "weekly" <door> because "The weekly email did not go out"
    Then one wake went on the site's queue for the Delivery "weekly"
    And it has the wake key the Delivery's own timer used, and the timer's request
    And Wake now answers in words that it was woken now by "edie@example.test" with the same key

    Examples:
      | door                |
      | on Today            |
      | on the command line |

  Scenario: Today offers Wake now beside an Overdue Delivery, with the command that does the same
    Given the Delivery "weekly" waits for its release at "2026-11-19T09:00:00Z" and its timer fired into a queue that lost it
    When an editor opens Today
    Then Today's Wake now for the Delivery "weekly" can be pressed, and names the command "papyrus agents wake-overdue --record Delivery --id weekly --reason TEXT"

  Scenario: Every request Wake now sends to the site's API is one the site's GraphQL schema accepts
    The fake site above answers whatever is asked, so a request AppSync would refuse could pass every scenario here and fail on a real site. The reads of one
    Delivery and one review request by id and the command line's request to the Automation page function are checked against the schema Amplify generates.
    When the Wake now requests are built against a recording site API
    Then every poke-in request is accepted by the GraphQL schema Amplify generates from the data schema
