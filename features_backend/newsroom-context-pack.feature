Feature: A reporting agent works from a context pack that knows the Story, the editor's direction and what the publication already covers
  When an editor selects a Story to research, a reporting agent is given one pack of text that is built the same way every time and
  needs no model to build. The system text says who the agent is and carries the publication's mission and policy and the Story's
  section mission, policy, assignment guidance and kill criteria; it is never shortened. The rest is layered from the most specific
  to the widest: the editor's assignment, the Story itself, the References already attached to it with the notes editors wrote on how
  they connect, the conversation on the Story, the research already done on it, then what the publication has published in the Story's section, the accepted References
  curated for that section, what it has published in other sections and the accepted References in other sections. There is no fixed
  count and no day window: the only bound is the character budget the caller gives, taken from the model's real limit. The first five
  layers are filled first; the room that is left is shared from the nearest ring outwards, each ring taking up to half of what remains,
  so the outer rings shrink first and are not starved. Every layer reports what it held and what it had to drop. Editors can attach a
  research assignment with their own direction to a Story, and the multi-search research run then uses the pack, so its queries and its
  synthesis know the Story and the publication's record. Nothing here calls a model or the network, and nothing is read outside the
  tenant the client is scoped to.

  Background:
    Given a newsroom with a publication policy, a section "law-policy" and a Story "story-1" in it
    And the editor's assignment "assignment-1" on the Story with the direction "Find the court rulings on model output"

  Scenario: The layers come in order, most specific first
    When the reporter context pack is built for the Story and the assignment
    Then the layers are, in order, "assignment, story, story_references, related_references, story_conversation, prior_research, desk_published, desk_references, publication_published, publication_references"
    And every layer holds at least one entry
    And the user text shows the editor's direction before the Story's draft and the Story's draft before the section's published record
    And the system text carries the role, the publication policy and the section mission

  Scenario: The system text is never trimmed, even under a tiny budget
    When the reporter context pack is built with a budget of 10 characters
    Then the system text is the same as without a budget
    And no outer layer holds an entry
    And the assignment and the Story are still complete

  Scenario: A section with no mission or policy is a warning, not an invented default
    Given the section has no mission and no policy
    When the reporter context pack is built for the Story and the assignment
    Then the warnings say that the section has no mission
    And the warnings say that the section has no policy
    And the system text does not contain the words "default mission"

  Scenario: Rejected and pending References never appear
    Given the section has an accepted, a pending and a rejected Reference
    When the reporter context pack is built for the Story and the assignment
    Then the Reference layers show the accepted Reference
    And the Reference layers do not show the pending Reference
    And the Reference layers do not show the rejected Reference

  Scenario: A Reference an editor voted on or rated ranks above an auto-accepted one
    Given the section has an auto-accepted Reference that is newer than every Reference an editor voted on
    When the reporter context pack is built for the Story and the assignment
    Then in the section's Reference layer the editor-rated Reference comes first
    And the editor-voted Reference with a written reason comes before the auto-accepted Reference
    And the auto-accepted Reference comes last

  Scenario: References connected to the Story's References are shown, strongest connection first
    When the reporter context pack is built for the Story and the assignment
    Then the layer of related References comes right after the Story's References
    And it holds the other end of edges in both directions, each once, and none already on the Story
    And the edge an editor accepted comes first, with the editor's note and the Reference it connects to
    And the suggested edges follow by descending score and are labelled with their score and curation status

  Scenario: Rejected edges and rejected References are never related, and nothing appears twice
    When the reporter context pack is built for the Story and the assignment
    Then a rejected edge and a rejected Reference never appear in the related layer
    And a Reference only a rejected edge connects is not in the related layer
    And no related Reference appears again in another layer

  Scenario: Earlier research on the Story is shown to the next reporter
    When the reporter context pack is built for the Story and the assignment
    Then the earlier research appears after the conversation with its direction, summary, claims and open questions

  Scenario: The section's References include those that other Stories in the section use as evidence
    When the reporter context pack is built for the Story and the assignment
    Then the section's Reference layer holds the Reference that another Story in the section uses as evidence

  Scenario: The outer layers are compact, one line for each entry
    When the reporter context pack is built for the Story and the assignment
    Then every entry in the outer layers is one line with its title, date and address
    And the first sentence of the summary or deck follows and the rest of it does not
    And an editor's reason and stars stay on an outer entry when present

  Scenario: A Reference whose title is only its address is not shown with that title
    When the reporter context pack is built for the Story and the assignment
    Then a Reference whose title is only its address shows no title line in the Story's References
    And in the outer layers such a Reference leads with the first sentence of its summary

  Scenario: Under a budget the outer rings shrink first and each keeps a share
    When the reporter context pack is built with room for the first five layers and 2500 more characters
    Then the assignment, the Story, its References, its conversation and its earlier research are all complete
    And each outer layer holds at least one entry

  Scenario: The nearest ring takes at most half of the room, so the next ring is not starved
    When the reporter context pack is built with room for the first five layers and 600 more characters
    Then the section's published layer used no more than half of the 600 characters
    And the section's Reference layer holds at least one entry

  Scenario: Whole entries only, and the dropped counts are reported
    When the reporter context pack is built with room for the first five layers and 2500 more characters
    Then every entry in the user text is complete
    And at least one outer layer reports a dropped count above zero with a reason
    And a layer that dropped nothing reports a dropped count of zero

  Scenario: When the first five layers alone do not fit, the oldest messages go first
    When the reporter context pack is built with room for the assignment and the Story only
    Then the conversation reports that its oldest messages were dropped
    And the References report that their summaries were dropped
    And the assignment and the Story are still complete

  Scenario: The hash is stable across runs and changes when the policy changes
    When the reporter context pack is built twice
    Then both packs have the same context hash
    When the publication policy is edited
    And the reporter context pack is built for the Story and the assignment
    Then the context hash changed
    And the editorial context hash changed

  Scenario: Another tenant's records are never read
    Given another tenant has a Story published in the same section and an accepted Reference there
    When the reporter context pack is built for the Story and the assignment
    Then nothing from the other tenant appears in the user text

  Scenario: A Story from another tenant cannot be packed
    Given the Story belongs to another tenant
    When the reporter context pack is built for the Story and the assignment
    Then building the pack fails because the tenant does not match

  Scenario: A Story with no section still gets the publication-wide layers
    Given the Story has no section
    When the reporter context pack is built for the Story and the assignment
    Then the section layers are empty and say the Story has no section
    And the warnings say that the Story has no section
    And the publication layers still hold entries

  Scenario: Assigning research links the assignment to the Story and moves an idea Story
    Given the Story is at the "idea" stage
    When an editor assigns research on the Story with the direction "Find the court rulings on model output"
    Then an assignment of type "research.multi" works on the Story's lineage in the Story's section
    And the assignment's instructions and metadata hold the direction
    And the assignment's context profile is "reporter" and its status is "open"
    And the assignment records a created event
    And the Story moved to the "assignment" stage

  Scenario: Assigning research leaves a Story that is past the idea stage where it is
    Given the Story is at the "reporting" stage
    When an editor assigns research on the Story with the direction "Find the court rulings on model output"
    Then an assignment works on the Story's lineage
    And the Story did not move

  Scenario: A dry run of assigning research writes nothing
    Given the Story is at the "idea" stage
    When an editor previews assigning research on the Story
    Then the preview wrote no record
    And the Story did not move

  Scenario: The research run uses the pack when the assignment works on a Story
    When the multi-search run is made for the assignment
    Then the planning and the synthesis were given the role and the policy as their system text
    And the planning brief is the pack's user text
    And the packet records the context hash, the editorial context hash and the size of each layer
    And the packet is on no message thread
    And the sources the run found are linked to the Story as consulted and not as cited
    And the Story's text is unchanged
    And the model is the default model

  Scenario: A source the Story already cites is not downgraded to consulted
    Given the Story already cites a Reference that the run finds again
    When the multi-search run is made for the assignment
    Then that Reference is still linked to the Story as cited

  Scenario: The research run is unchanged when no Story is linked
    Given the assignment is a plain multi-search assignment with no Story
    When the multi-search run is made for the assignment
    Then the planning brief is the assignment's own brief text
    And the planning system text is the plain planning prompt
    And the packet has no context pack record
