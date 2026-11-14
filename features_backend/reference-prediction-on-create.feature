@backend @reference-prediction
Feature: A Reference created without a prediction gets one, requested once by the event that creates it
  The References page and the public pages show a pending Reference only when the site's Cyclotron has predicted it: an unpredicted Reference is not the same as a fifty
  percent one, and nothing is shown until there is a number. Until now only two things recorded a prediction: the monitoring router when it delivered a Reference, and the
  sweep a person runs by hand. A Reference an editor pasted into the console, one a catalog import created, one chat created, one a research packet registered or one an
  inbound email registered never had one, so on Machines on Machines one hundred and seventy three of them would never appear. The site's Cyclotron is a hosted service that
  only the router can reach, and the code that creates a Reference does not run there. So the code that creates a Reference asks the router, once, through the lane the
  editor-selected email imports already use: one row per Reference in the monitoring table's own partition, on the index that table already has. The router decides it the
  way it decides a monitor's item, except that the input is the Reference's title and address (no page is fetched and no summary model runs), and records the decision with
  the same builders a delivery uses: the decision relation, the probability, the time and the sort key on the Reference itself. The Reference is never changed otherwise:
  not its vote, not its status. Deciding is not training: nothing is sent back to the Cyclotron. A Reference that already has a prediction is not decided again, and one
  that has a decision but no number on its row gets the number copied. Nothing walks a corpus to find References that lack a prediction; the only way to find the ones that
  predate this rule is a command a person runs by hand. If the request cannot be made, the Reference still exists, stays hidden, and the person who created it is told
  plainly and shown the command that asks again. If the Cyclotron cannot be reached, the request keeps its place and is retried with a growing delay by the router. The
  monitoring table, the machine API and the publication's data API are fakes in these scenarios.

  Scenario: A Reference created without a prediction is asked about once and the request creates nothing else
    Given a pending Reference with no prediction
    When a route that created it asks for its prediction twice
    Then there is exactly one queued request for it and the publication's data was not written

  Scenario: The router decides the request and records it the way a delivery does
    Given a pending Reference with no prediction
    And a route that created it asks for its prediction
    When the router works through the queued requests
    Then the Reference has a probability, a time and a sort key, and one current decision relation
    And its vote and status are unchanged and the request has left the lane

  Scenario: Deciding is not training
    Given a pending Reference with no prediction
    And a route that created it asks for its prediction
    When the router works through the queued requests
    Then the Cyclotron was asked to decide once and was sent no feedback
    And the decision input was the title and address with no summary

  Scenario: A Reference that already has a prediction is not decided again
    Given a pending Reference that already has a prediction
    And a route that created it asks for its prediction
    When the router works through the queued requests
    Then the Cyclotron was not called and the earlier prediction stands

  Scenario: A decision without a number on the row gets the number copied
    Given a pending Reference with no prediction
    And its request was decided and the numbers were then removed from the row
    When the router works through a second request for it
    Then the Cyclotron was not called again and the row has its probability back

  Scenario: An unreachable Cyclotron keeps the Reference hidden and the request retried
    Given a pending Reference with no prediction
    And a route that created it asks for its prediction
    And the Cyclotron is not ready to decide
    When the router works through the queued requests
    Then the Reference still has no prediction and its request is still queued
    And later, when the Cyclotron answers, the Reference is predicted and the request is gone

  Scenario: A request that cannot be made is reported to the person who made it, never swallowed
    Given an import that created a pending Reference
    When the publication is not served by the cloud router
    Then the answer says plainly that the prediction was not requested, names the command that asks again, and nothing was raised

  Scenario: A catalog import of many is queued, not decided in the request
    Given an import that created thirty pending References
    When the route asks for their predictions
    Then thirty requests are queued with one conditional write each and no decision was made in the request
    And the router decides them within its own time and stops, without loss, when that time is up

  Scenario: A monitor that has stopped deciding leaves the requests waiting
    Given a pending Reference with no prediction
    And a route that created it asks for its prediction
    When the monitor is changed to deliver by rule and the router works through the queued requests
    Then the Cyclotron was not called and the request is still queued

  Scenario: Requests queued in the partition the sites use by default are drained by a schedule
    Given the partition every site backend queues prediction requests into by default
    Then the monitoring stack has a five minute schedule that runs the email-references task for that same partition

  Scenario: A Reference that is already accepted still gets a prediction request
    Given a Reference that an import created already accepted and that has no prediction
    Then it is one of the References a prediction is requested for
