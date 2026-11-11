@backend @concept-tags
Feature: An editor or an agent tags a story or a Reference with an existing concept, and nothing else
  A story or a Reference is tagged with a concept by one edge: `tagged_with`, from the story or Reference to an accepted SemanticNode, current, with
  `provenance` human (a signed-in person) or derived (an agent) and the kind `item.concept` or `reference.concept`. `mentions` stays for text the enrichment
  found, and `related_to` is the tag's older name: rows under it still exist and every reader accepts both until they are migrated. The commands
  `papyrus stories link-concept` and `papyrus references link-concept`, and the agent tool `papyrus_link_concepts`, are the rigid way in: no option or field
  chooses a predicate or a state, a concept is never created, and a name must match exactly (node key, hashtag, or name or alias, ignoring case) or the
  command lists the closest accepted concepts. A tag that already exists in any accepted form is left alone, and a tag a person rejected stays rejected.
  Each concept line says whether it has a public wiki page, because a story shows a concept as a link only once a page exists. `papyrus stories check-links`
  and `papyrus references check-links` list what is not the official shape. Nothing here reaches a real site, login or AWS.

  Background:
    Given a site with a published article "A big story", an accepted Reference, and these concepts: an accepted "Voice Cloning" with a public page, an accepted "Unpublished idea" with none, accepted "Translation" concepts of three kinds, and a rejected "Spam"

  Scenario: An editor tags a story with a concept by hashtag
    When a signed-in editor "Grace Editor" tags the story "big" with the concept "#voice-cloning"
    Then the tagging succeeds and prints "write" for "Voice Cloning" with a public page
    And the story has one current "tagged_with" edge to "editor_concept--voice-cloning", kind "item.concept", provenance "human", added by "Grace Editor"
    And no concept was created

  Scenario: An editor tags a Reference the same way
    When a signed-in editor "Grace Editor" tags the Reference "reference-a" with "Voice Cloning"
    Then the tagging succeeds and prints "write" for "Voice Cloning" with a public page
    And the Reference has one current "tagged_with" edge, kind "reference.concept"

  Scenario: A concept without a public page is tagged with a plain warning
    When a signed-in editor "Grace Editor" tags the story "big" with the concept "#unpublished"
    Then the tagging succeeds and prints "write" for "Unpublished idea" with no public page
    And it warned that "Unpublished idea" has no public wiki page yet

  Scenario: A name shared by several kinds lists them and asks for a node key
    When a signed-in editor "Grace Editor" tags the story "big" with the concept "#translation"
    Then the tagging fails naming "task--translation", "concept--translation" and "editor_concept--translation"
    And no tag was written

  Scenario: An unknown name lists the closest accepted concepts and creates nothing
    When a signed-in editor "Grace Editor" tags the story "big" with the concept "voice cloner"
    Then the tagging fails with "No accepted concept is named"
    And it lists "editor_concept--voice-cloning" as a close match
    And no concept was created
    And no tag was written

  Scenario: A rejected concept is refused
    When a signed-in editor "Grace Editor" tags the story "big" with the concept "concept--spam"
    Then the tagging fails with "status rejected"
    And no tag was written

  Scenario: Repeating a tag, or a tag that exists under the older name, writes nothing
    Given the story "big" is already tagged with "Voice Cloning" under the older name "related_to"
    When a signed-in editor "Grace Editor" tags the story "big" with the concept "#voice-cloning"
    Then the tagging succeeds and prints "exists" for "Voice Cloning" with a public page
    And the only edge is still the "related_to" one

  Scenario: A tag a person rejected stays rejected
    Given the story "big" has a rejected tag for "Voice Cloning"
    When a signed-in editor "Grace Editor" tags the story "big" with the concept "#voice-cloning"
    Then the tagging succeeds and prints "rejected" for "Voice Cloning" with a public page
    And the edge is still rejected

  Scenario: No option can choose the predicate, the state or a new concept
    When a signed-in editor "Grace Editor" tags the story "big" with "#voice-cloning" passing the option "--predicate mentions"
    Then the tagging fails with "is not accepted"
    And no tag was written

  Scenario: The audit lists what is not the official shape
    Given the story "big" is already tagged with "Voice Cloning" under the older name "related_to"
    When an editor audits the links of the story "big"
    Then the audit lists the problem "legacy: migrate"
