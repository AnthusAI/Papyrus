Feature: An editor lists the concepts a section should be especially aware of, and every agent in the section reads them
  Each section can track concepts: the editor's own example is the confinement problem and the containment problem in a security section.
  The list is stored on the section as its tracked concepts, each with the editor's note, who added it and when. The command line lists
  the concepts, adds one by a name, an alias, a hashtag or a node key, makes a new editor concept only when asked, and removes one; it writes
  unless it is asked for a dry run. Every agent's context pack then carries one card for each tracked concept, with its aliases, kind,
  description, the editor's note and its links to other concepts, and a ring of the accepted References that are tagged with or mention a
  tracked concept. A concept that no longer resolves or was rejected is a warning, never a card. A site whose data API predates the field
  reads as tracking nothing. Nothing here calls a model or the network.

  Background:
    Given a newsroom whose section "law-policy" tracks one concept and a Story "story-1" in it

  Scenario: The command lists what the section tracks
    When the editor lists the concepts the section tracks
    Then the list shows the concept "containment problem" as tracked

  Scenario: A concept is added by name with the editor's note
    Given the newsroom knows a concept "confinement problem" with the alias "boxing"
    When the editor adds the concept "confinement problem" with the note "The sibling of containment"
    Then the section tracks both concepts in the order they were added
    And the new entry holds the note, who added it and when

  Scenario Outline: A concept can be named in any of its forms
    Given the newsroom knows a concept "confinement problem" with the alias "boxing"
    When the editor adds the concept "<form>"
    Then the section tracks the concept "confinement problem"

    Examples:
      | form                                   |
      | Confinement Problem                    |
      | boxing                                 |
      | #confinement-problem                   |
      | editor_concept--confinement-problem    |

  Scenario: An unknown name fails unless the editor asks for the concept to be made
    When the editor adds the concept "the sandbox problem"
    Then the command is refused saying "add --create"
    And the section still tracks one concept
    When the editor adds the concept "the sandbox problem" asking to create it
    Then the section tracks the concept "the sandbox problem"
    And the newsroom holds an editor concept written exactly as the shared fixture says

  Scenario: A rejected concept cannot be added
    Given the newsroom knows a rejected concept "confinement problem"
    When the editor adds the concept "confinement problem"
    Then the command is refused saying "was rejected"

  Scenario: A dry run changes nothing
    Given the newsroom knows a concept "confinement problem" with the alias "boxing"
    When the editor adds the concept "confinement problem" as a dry run
    Then the section still tracks one concept
    And the newsroom has written nothing

  Scenario: A concept is removed, even one that has since been rejected
    Given the newsroom knows a concept "confinement problem" with the alias "boxing"
    And the section tracks "confinement problem" too
    When the editor removes the concept "boxing"
    Then the section still tracks one concept
    When the concept "containment problem" is rejected
    And the editor removes the concept "containment problem"
    Then the section tracks no concepts

  Scenario: Every profile reads one card for each tracked concept
    Given the tracked concept has an alias, a description and the editor's note "Why it matters here"
    And the concept is linked to another concept by a suggestion and by a link an editor accepted with the note "Two sides of one fence"
    When the context pack is built for each of the reporter, the copywriter and the editor on the Story
    Then each pack's section concepts layer holds a card for "containment problem"
    And the card shows the alias, the kind, the description and the editor's note
    And the card lists the accepted link with its note before the suggested one
    And the section concepts come before the section's published Stories in every pack

  Scenario: A tracked concept that is gone or rejected is a warning and not a card
    Given the section also tracks a concept that no longer exists
    And the tracked concept "containment problem" is rejected
    When the reporter context pack is built for the Story
    Then the section concepts layer holds no card
    And the warnings name both concepts

  Scenario: References tagged with or mentioning a tracked concept are a ring, best first
    Given an accepted Reference mentions the tracked concept and an editor-rated Reference is tagged with it
    When the reporter context pack is built for the Story
    Then the concept References layer lists the editor-rated one first, labelled "containment problem (tagged)"
    And the mention is labelled "containment problem (mentioned)"
    And a pending Reference tagged with the concept is not listed

  Scenario: The Story's own References are left out of the concept ring
    Given the Story's own Reference is tagged with the tracked concept
    When the reporter context pack is built for the Story
    Then the concept References layer does not list the Story's own Reference

  Scenario: A section that tracks nothing says why
    Given the section tracks no concepts
    When the reporter context pack is built for the Story
    Then both concept layers are empty with the reason "the section tracks no concepts"

  Scenario: A site that predates the field is read without it
    Given a site whose schema has no tracked concepts on a section
    When the router reads that site's sections twice
    Then both reads return the sections and the field was asked for once

  Scenario: The command line and the hashtag box make the same concept
    Then the Python writer produces every editor concept in the shared fixture
