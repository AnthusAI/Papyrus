Feature: Automated runs never change a concept that already exists
  A concept is a node in the knowledge graph, and people edit concepts in the wiki: its name, its description, its aliases.
  An automated writer, a knowledge run or an import, must never undo those edits. A run gets or creates the concept: when the
  concept is missing it creates it, when it exists it leaves it alone, and either way it writes the associations to it. The
  only things a machine may keep updating on an existing concept are the numbers worked out from the graph and the
  extractor's page answer (an editor's own decision on the page is kept elsewhere and wins), each as a partial
  update that names only those fields. Three exceptions are kept: a generated concept becomes accepted when a published
  Story's front matter names it, the acceptance mark on a concept that same path created, and a generated concept becomes
  accepted when a monitor record names it. None of them ever touches a rejected concept.

  Scenario: A concept a person edited keeps its name, description and aliases through a run
    Given the concept run knows an edited concept named "Voice cloning (edited)" with the alias "Voice Cloning"
    When the concept run imports a graph that names "Voice Cloning"
    Then the concept run writes no concept
    And the concept run names the edited concept as the target of the association

  Scenario: A new mention of an existing concept writes the association and no node
    Given the concept run knows an edited concept named "Voice cloning (edited)" with the alias "Voice Cloning"
    When the concept run imports a graph that names "Voice cloning (edited)"
    Then the concept run writes no concept
    And the concept run names the edited concept as the target of the association

  Scenario: A mention of an unknown concept creates the concept and the association
    When the concept run imports a graph that names "Brand New Idea"
    Then the concept run creates exactly one concept, create-only, named "Brand New Idea"
    And the concept run names the created concept as the target of the association

  Scenario: Matching by alias reuses the node
    Given the concept run knows an edited concept named "Voice cloning (edited)" with the alias "vc"
    When the concept run imports a graph that names "VC"
    Then the concept run writes no concept

  Scenario: A rejected concept is not revived or linked
    Given the concept run knows a rejected concept named "Spam Topic"
    When the concept run imports a graph that names "Spam Topic"
    Then the concept run writes no concept
    And the concept run writes no association

  Scenario: The derived numbers update without touching anything else
    Given the concept run knows an edited concept named "Voice cloning (edited)" with the alias "Voice Cloning"
    When the concept run recomputes the authority numbers with a score of 0.5 and a relation count of 3
    Then the concept run sends a partial update naming only the derived fields
    And the edited concept still has its own name, description and aliases

  Scenario: Two imports of one concept make one node
    When the concept run imports a graph that names "Brand New Idea"
    And the concept run imports a second graph that names "brand  new idea"
    Then both imports plan the same concept id

  Scenario: Earlier imports are not superseded
    Then an import of a graph never supersedes the concepts of earlier imports

  Scenario: A generated concept becomes accepted when a published Story's front matter names it
    Given the concept run knows a generated concept named "Voice Cloning"
    When a published Story's front matter names the concept "Voice Cloning" of kind "concept"
    Then the concept run accepts the concept and changes nothing else about it

  Scenario: A rejected concept is not accepted by a Story's front matter
    Given the concept run knows a rejected concept named "Voice Cloning"
    When a published Story's front matter names the concept "Voice Cloning" of kind "concept"
    Then the concept run writes no concept and sends no update

  Scenario: The acceptance mark is recorded on a concept the front matter path created
    Given the concept run knows a concept the front matter path created without an acceptance mark
    When a published Story's front matter names the concept "Voice Cloning" of kind "concept"
    Then the concept run sends one update that only records the acceptance mark

  Scenario: A generated concept becomes accepted when a monitor record names it
    Given the concept run knows a generated concept named "text-to-speech"
    When a monitor record names the task "text-to-speech"
    Then the concept run accepts the concept and changes nothing else about it

  Scenario: A rejected concept is not accepted by a monitor record
    Given the concept run knows a rejected concept named "text-to-speech"
    When a monitor record names the task "text-to-speech"
    Then the concept run sends no update to the concept
