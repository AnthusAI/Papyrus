Feature: The router speaks Cyclotron's decision contract
  Cyclotron is a general decision engine, so its machine API names bindings, callers and reviewers rather
  than publications and editors. The router sends every request in that contract, cyclotron-decision/v1: a
  story for one publication goes to that publication's binding route, a story for several goes to the
  combined decisions route, and an editor's vote is sent as feedback naming the calling site and a reviewer
  that is never an email address. Papyrus keeps its own names: a publication's binding is still configured
  by its publicationId. A combined job the router posted before the switch still answers in the publication
  contract, and so does its decision-ready event; the router reads those answers too, so no story is posted
  again or lost while the old jobs finish.

  Scenario: A story for several publications is decided in the decision contract
    Given a router for three publications with a combined Cyclotron endpoint
    And the monitor has collected a story that every publication could use
    When the router decides the collected story
    Then the router posted one combined decision in the decision contract
    And the story is routed and delivered to every publication that includes it

  Scenario: A story for one publication is decided on its binding route
    Given a router for one publication with a combined Cyclotron endpoint
    And the monitor has collected a story that every publication could use
    When the router decides the collected story
    Then the router posted the story to the publication's binding route in the decision contract
    And the story is routed and delivered to every publication that includes it

  Scenario: A combined job posted before the switch is collected from its old-shaped answer
    Given a router for three publications with a combined Cyclotron endpoint
    And the monitor has collected a story that every publication could use
    And Cyclotron answers the combined job in the publication contract
    When the router decides the collected story
    Then the story is routed and delivered to every publication that includes it
    And the router posted the story only once

  Scenario: An editor's vote is sent with the calling site and a reviewer that is not an email address
    Given a router and three delivered stories
    When an editor accepts a reference in the newsroom UI
    And the feedback task runs
    Then the feedback names the calling site and a reviewer in the decision contract
