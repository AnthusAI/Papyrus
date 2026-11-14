@backend @suggest-links
Feature: A person or a model judges a short ranked list of related content that was computed from the story's concepts
  Linking a story to related articles, posts and References starts from the story's concepts and costs no model tokens. `papyrus stories suggest-links` takes
  the story's concepts (a curated tag weighs 1.0, an accepted mention 0.4), adds the concepts near them in two hops (an editor-confirmed concept link about 0.5,
  a concept that appears together with it about 0.3 times its lift-based strength), and scans those for the published articles, posts and accepted
  References that carry them. Each shared concept counts by how rare it is, so a concept carried by a quarter of all stories counts for little. Nothing is
  written: each candidate carries the exact link command. `papyrus knowledge concepts related` shows the first hop for one concept, and `papyrus knowledge
  concepts search` finds accepted concepts by meaning, never by popularity. Nothing here reaches a real site, login, model or AWS.

  Background:
    Given a stand-in site with stories, References and concepts for link suggestions

  Scenario: Candidates are ranked by the rare concepts they share and each carries its link command
    When I ask for link suggestions for the story "s0"
    Then the first article is "Voice clones and your privacy" with the shared concepts and a "papyrus stories link-story" command
    And the first related finding carries a "--reference" command
    And no row was written to the site

  Scenario: Content that is already linked, unpublished or not accepted is left out
    When I ask for link suggestions for the story "s0"
    Then no candidate is the story itself, a story already linked by see also, a draft story, a Reference already used as evidence, or a Reference that is not accepted

  Scenario: A second-hop candidate names the path that found it
    When I ask for link suggestions for the story "s0"
    Then the article "Via the neighbour" is found "via Acoustic Side Channel, then Speech Synthesis"

  Scenario: The concepts near a concept come with the reason
    When I ask for the concepts related to "#sound"
    Then the first related concept is "Speech Synthesis", confirmed, with the explanation an editor wrote

  Scenario: A concept search is ordered by meaning and an exact name comes first
    Given a concept index in which "Privacy" is far from the question but named exactly
    When I search the concepts for "Privacy"
    Then the first result is "Privacy" as a name match
    When I search the concepts for "acoustic leakage"
    Then the first result is "Acoustic Side Channel" as a meaning match
    And the popular concept "AI" is shown with its counts but ranks lower

  Scenario: Duplicates are flagged and a stale index is said plainly
    Given a second accepted concept with the same name as "Voice Cloning"
    When I search the concepts for "voice"
    Then both are flagged as possible duplicates of each other
    When the index holds a vector for only two of the accepted concepts
    Then the search warns that the index is stale and prints the vector-index command
