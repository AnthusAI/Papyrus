@brand-agnostic
Feature: A story shows the Reference it is based on, and the Reference shows its stories
  A story that the newsroom made from a Reference is linked to it. In the newsroom, a story's References view lists the
  Reference with its title, the site that published it, its preview image and a link that opens the Reference; the link also
  leads to the original page. The story is marked "Based on" in words and with an icon, never by colour alone, and the view says
  that the story's text is our own. The Reference's own page lists the stories based on it, each opening the story. These
  scenarios run in demo mode with in-memory data.

  Scenario: The story view shows the Reference the story is based on
    Given I open the demo story that is based on a Reference at 1280 by 900
    When I open the story's References view
    Then the References view should list the Reference "Foundation Model Scaling Retrospective"
    And the Reference should show its site "history.example.org" and its preview image
    And the Reference should be marked "Based on" with an icon
    And the References view should say that the story's text is our own
    And the Reference should offer a link that opens it

  Scenario: The Reference card has no border or outline
    Given I open the demo story that is based on a Reference at 1280 by 900
    When I open the story's References view
    Then the Reference card should have no border or outline

  Scenario: The Reference view lists the stories based on it
    Given I open the demo Reference that a story is based on at 1280 by 900
    Then the Reference view should list the story "Harbor Cranes Return" as "Based on"
    And the story should link to its own page

  Scenario: A story that is not based on a Reference has an empty References view
    Given I open the demo story that has no Reference at 1280 by 900
    When I open the story's References view
    Then the References view should list no Reference
