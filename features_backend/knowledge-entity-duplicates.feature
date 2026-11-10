Feature: The map keeps one entity for one thing, however the sources spell its name
  The extractor meets a thing under several names in a week: "The NTSB" in one source and
  "National Transportation Safety Board" in another, "MCP" beside "Model Context Protocol", a
  person by surname in one paragraph and by full name in the next, a leading "And" the
  extractor kept from the sentence before the name. The registry resolves only the names an
  entity already holds, and the AI review accepts whatever it is shown, so the Machines on
  Machines map collected about seventeen pairs that are one thing each.

  A duplicate check now runs before a second entity is made or accepted, on both paths: when
  the knowledge run would make an entity from an extractor candidate, and when the AI review
  would accept a generated one. The rules are data (data/entity-duplicate-rules.yml): the same
  name ignoring case and punctuation, the same name once a leading article or conjunction is
  taken off, an acronym that is the initials of a longer name of the same kind, a single word
  that is the surname of exactly one full-name person, and, for organizations, a name that is
  a whole-word start or end of another. A name that is only another spelling is linked to the
  entity and added to it as an alias. A name that merely looks the same makes no entity and
  no link, and a proposal is filed for a person. The same name in two different kinds is never
  a duplicate; it is an ambiguity, which "entities add" tags with the Disambiguation concept.

  Three commands finish the job for entities already on the map: "entities add" creates an
  accepted entity with all its aliases at once, "entities merge" joins two entities that are
  one thing, and "entities duplicates" reports the pairs the rules catch without changing
  anything. Writing commands write unless "--dry-run" is given.

  Background:
    Given a site "shipped" with the published items "alpha" and "beta"

  Scenario: A name that is only another spelling is linked to the entity and becomes its alias
    Given the map holds the accepted organization "The UK AI Security Institute"
    When the extractor brings the organization "And the UK AI Security Institute" in the item "alpha" and the run is imported for the corpus "shipped"
    Then the map still has one entity named "The UK AI Security Institute"
    And "The UK AI Security Institute" has the alias "And the UK AI Security Institute"
    And "The UK AI Security Institute" is mentioned in the item "alpha"
    And the import report says the duplicate was resolved

  Scenario Outline: A name that looks the same makes no entity and files a proposal for a person
    Given the map holds the accepted <kind> "<existing>"
    When the extractor brings the <kind> "<brought>" in the item "alpha" and the run is imported for the corpus "shipped"
    Then the map still has one entity named "<existing>"
    And "<existing>" is mentioned in no item
    And one proposal asks a person whether "<brought>" is "<existing>"
    And the import report says the duplicate was proposed

    Examples:
      | kind         | existing                                | brought |
      | organization | The National Transportation Safety Board | The NTSB |
      | software     | The Model Context Protocol              | MCP |
      | organization | Redwood Research                        | Redwood |
      | person       | Dario Amodei                            | Amodei |
      | person       | Elon Musk                               | Musk |

  Scenario Outline: Things that are different stay different
    Given the map holds the accepted <kind> "<existing>"
    When the extractor brings the <kind> "<brought>" in the item "alpha" and the run is imported for the corpus "shipped"
    Then the map has an entity named "<existing>" and an entity named "<brought>"
    And no proposal was filed

    Examples:
      | kind    | existing               | brought |
      | concept | Reinforcement learning | RLHF |
      | model   | AlphaGo                | AlphaGo Zero |
      | model   | GPT-Rosalind           | GPT-Rosalind-5.5 |

  Scenario: A surname shared by two full-name people is not taken for either
    Given the map holds the accepted person "John Smith"
    And the map holds the accepted person "Jane Smith"
    When the extractor brings the person "Smith" in the item "alpha" and the run is imported for the corpus "shipped"
    Then the map has an entity named "Smith"
    And no proposal was filed

  Scenario: The same name in another kind is not a duplicate
    Given the map holds the accepted model "Mistral"
    When the extractor brings the maker "Mistral" in the item "alpha" and the run is imported for the corpus "shipped"
    Then the map has 2 entities named "Mistral"
    And no proposal was filed

  Scenario: Running the import again files nothing new and leaves a person's decision alone
    Given the map holds the accepted organization "Redwood Research"
    And the extractor brought the organization "Redwood" in the item "alpha" and the run was imported for the corpus "shipped"
    And a person rejected the proposal about "Redwood"
    When the extractor brings the organization "Redwood" in the item "alpha" and the run is imported for the corpus "shipped"
    Then one proposal asks a person whether "Redwood" is "Redwood Research"
    And that proposal is still rejected

  Scenario: The AI review holds back a generated entity that duplicates an accepted one
    Given the map holds the accepted organization "Redwood Research"
    And the map holds the generated organization "Redwood"
    When the AI review would accept every generated entity on a quote
    Then the AI review left "Redwood" generated and unsure because it may duplicate "Redwood Research"
    And one proposal asks a person to merge "Redwood" into "Redwood Research"

  Scenario: The AI review still accepts an entity that duplicates nothing
    Given the map holds the accepted organization "Redwood Research"
    And the map holds the generated organization "Pilot Lab"
    When the AI review would accept every generated entity on a quote
    Then the AI review accepted "Pilot Lab"
    And no proposal was filed

  Scenario: Adding an entity creates it accepted with all its aliases
    When an agent adds the organization "National Transportation Safety Board" with the aliases "NTSB" and "The NTSB"
    Then the map has the accepted organization "National Transportation Safety Board" with the aliases "NTSB, The NTSB"
    And the entity was accepted by the AI agent

  Scenario: Adding an entity that exists accepts it and adds only the aliases it lacks
    Given the map holds the generated software "Model Context Protocol"
    When an agent adds the software "Model Context Protocol" with the alias "MCP"
    Then the map has the accepted software "Model Context Protocol" with the aliases "MCP"
    When an agent adds the software "Model Context Protocol" with the alias "MCP"
    Then no record was changed

  Scenario: Adding an entity that duplicates an accepted one is refused
    Given the map holds the accepted person "Elon Musk"
    When an agent adds the person "Musk"
    Then the entity command is refused with "looks like 'Elon Musk'"
    And the map has no entity named "Musk"

  Scenario: Adding an entity with a dry run writes nothing
    When an agent previews adding the organization "National Transportation Safety Board" with the alias "NTSB"
    Then no record was changed
    And the preview says the entity would be created

  Scenario: An ambiguous name is tagged with the Disambiguation concept in code
    Given the map holds the accepted maker "Mistral"
    When an agent adds the model "Mistral"
    Then the Disambiguation concept was made
    And the maker "Mistral" and the model "Mistral" are each linked to the Disambiguation concept with a note that says they must not be merged

  Scenario: A name that is unique gets no Disambiguation tag
    When an agent adds the model "Gemma 3"
    Then nothing was linked to the Disambiguation concept

  Scenario: Merging joins two entities that are one thing
    Given the map holds the accepted person "Elon Musk"
    And the map holds the accepted person "Musk"
    And "Musk" is mentioned in the item "alpha"
    When a person merges "Musk" into "Elon Musk"
    Then "Elon Musk" has the alias "Musk"
    And "Musk" is no longer a current entity
    And "Elon Musk" is mentioned in the item "alpha"
    And no current link touches "Musk"
    And the merge output says the page is taken down by "wiki sync --retire"

  Scenario: Merging keeps the survivor's own link when both entities were mentioned in the same item
    Given the map holds the accepted person "Elon Musk"
    And the map holds the accepted person "Musk"
    And "Elon Musk" is mentioned in the item "beta"
    And "Musk" is mentioned in the item "beta"
    When a person merges "Musk" into "Elon Musk"
    Then "Elon Musk" is mentioned in the item "beta" once

  Scenario: Merging with a dry run writes nothing
    Given the map holds the accepted person "Elon Musk"
    And the map holds the accepted person "Musk"
    When a person previews merging "Musk" into "Elon Musk"
    Then no record was changed

  Scenario: Merging is refused across kinds and into an unaccepted entity
    Given the map holds the accepted person "Elon Musk"
    And the map holds the accepted organization "Musk"
    And the map holds the generated person "Musk Jr"
    When a person merges the organization "Musk" into "Elon Musk"
    Then the entity command is refused with "different kinds"
    When a person merges "Elon Musk" into the generated "Musk Jr"
    Then the entity command is refused with "not accepted"

  Scenario: The duplicates report lists the pairs and changes nothing
    Given the map holds the accepted organization "National Transportation Safety Board"
    And the map holds the accepted organization "NTSB"
    And the map holds the accepted model "AlphaGo"
    And the map holds the accepted model "AlphaGo Zero"
    When an agent asks for the duplicates
    Then the report lists "organization--ntsb" as a duplicate of "organization--national-transportation-safety-board"
    And the report does not list "AlphaGo Zero"
    And no record was changed

  Scenario: The rules are data
    Then the duplicate rules file lists the rules "same_name, leading_word, acronym, surname, containment"
    And the rule "containment" applies only to organizations and the rule "surname" only to people
