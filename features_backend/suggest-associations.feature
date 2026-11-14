@backend @suggest-associations
Feature: An item's own text is enough to find the concepts, stories, posts and References it should be associated with
  An agent should not have to invent search phrases. `papyrus stories suggest-associations --story X` (or `--reference X`) builds one query from the item
  (its title, its summary, the first words of its body) and finds the accepted concepts that text names: a concept's name, alias or #hashtag, matched as whole
  words, ranked by how rare the concept is and where it appears (title over summary over body). That needs no model and no embedding key, so it works for a
  signed-in editor. When the shell does have a key and a vector index, the concepts nearest by meaning are added; otherwise one line says so. The best concepts
  then start the same graph pass as `stories suggest-links`, so related stories, posts and References are ranked even before the item has a tag. Each concept and
  candidate carries the exact command that links it. Nothing is written. The command knows nothing about a site's sections or publication types. Nothing here
  reaches a real site, login, model or AWS.

  Background:
    Given a stand-in site with stories, References and concepts for link suggestions

  Scenario: An untagged story gets concept candidates from its text and related items from those concepts
    Given the untagged story "s9" has a title about privacy and voice cloning
    When I ask for associations for the story "s9"
    Then the candidate concepts include "Privacy" and "Voice Cloning" with a "papyrus stories link-concept" command
    And related items are ranked from those concepts with a "papyrus stories link-story" command
    And no row was written to the site

  Scenario: A concept in the title ranks above one only in the body
    Given the untagged story "s9" has "Voice Cloning" in the title and "Privacy" only in the body
    When I ask for associations for the story "s9"
    Then "Voice Cloning" ranks above "Privacy"

  Scenario: A tagged story ranks related items as suggest-links does
    When I ask for associations for the story "s0"
    Then its already tagged concepts are not offered again as a link command
    And the first related article is the one "stories suggest-links" ranks first

  Scenario: A Reference is read from its own text and tags and nothing is written
    When I ask for associations for the Reference "ref-1"
    Then the item is a Reference and related stories carry a command that links them to it
    And no row was written to the site

  Scenario: No embedding key is needed
    Given this shell has no embedding key
    When I ask for associations for the story "s9"
    Then the result says in one line that concepts were matched by name only

  Scenario: A short concept name does not match inside a longer word
    Given the untagged story "s9" mentions "paid" and "said" but not the concept "AI"
    When I ask for associations for the story "s9"
    Then "AI" is not a candidate concept
