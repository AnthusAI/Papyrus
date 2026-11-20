@backend @editor-concepts
Feature: A concept an editor invents by typing its hashtag is a real concept everywhere
  An editor can type a hashtag that no concept has, such as #fake-website-networks, and tag a Reference with it in one step. The concept is made on the spot with
  the name and nothing else (an editor adds a description on its page later) and has the kind "editor concept". It is a real concept: it gets a concept card (its
  name at minimum, and its description once there is one) and so shows up in the suggestions for other References, the idea packs read its tags as the human
  signal they are, and the knowledge run leaves it alone. Nothing publishes it on the public wiki until the site's vocabulary names the kind.

  Scenario: The concept kind is a concept for cards and suggestions
    Given the editor concept "fake website networks" next to an author and a coverage question
    When the concept cards are prepared for those nodes
    Then the editor concept has a card and the author and the coverage question have none
    And the card of the editor concept names the concept

  Scenario: A description is added to the card once an editor writes one
    Given the editor concept "fake website networks" with the description "Sites that exist to look like independent news."
    When the concept cards are prepared for those nodes
    Then the card of the editor concept holds the description

  Scenario: A Reference an editor tagged is read as one a person worked on
    Given 3 accepted References of which an editor tagged one with the editor concept and the machine suggested it for another
    When the idea signals read the site
    Then only the tagged Reference has its concept links read

  Scenario: Typing a new hashtag makes the concept and a confirmed human link in one step
    When an editor types the hashtag "#Fake Website Networks" on a Reference
    Then a concept "fake website networks" of the kind editor concept exists with the key "editor_concept--fake-website-networks", accepted, with who made it and when and no description
    And the Reference has one current tagged_with link to it, made by a person and confirmed

  Scenario: Typing the same name again, in any case, tags with the same concept
    When an editor types the hashtags "#fake-website-networks" and "FAKE website NETWORKS" on a Reference
    Then there is one concept and one link

  Scenario: An editor describes the concept later
    When an editor types the hashtag "#fake-website-networks" on a Reference and later describes it as "Sites made to look like news."
    Then the concept holds those words and who wrote them
