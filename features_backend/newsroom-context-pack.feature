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
    Then the layers are, in order, "assignment, story, process, audience_lenses, story_references, related_references, story_conversation, prior_research, section_concepts, concept_references, desk_published, desk_references, publication_published, publication_references"
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

  Scenario: The editor's direction outranks the Story in the planning and synthesis prompts
    When the multi-search run is made for the assignment
    Then the planning and synthesis prompts tell the model that the editor's direction outranks the Story
    And the brief begins with the editor's direction, labelled as the editor's, before the Story

  Scenario: A run with no Story keeps the plain prompts
    Given the assignment is a plain multi-search assignment with no Story
    When the multi-search run is made for the assignment
    Then the plain prompts carry no direction rules

  Scenario: A run on a Story takes in only the sources a claim cites
    When the multi-search run is made for the assignment
    Then the intake is told to take in only the sources a claim cites

  Scenario: A run with no Story takes in every source as before
    Given the assignment is a plain multi-search assignment with no Story
    When the multi-search run is made for the assignment
    Then the intake is not told to take in only cited sources

  Scenario: Cited-only intake registers cited sources once, as pending, and leaves held References alone
    Given an earlier packet of seven sources, three cited, one of them already held as an accepted Reference
    When the packet's sources are taken in with the cited-only option
    Then only the cited sources not already held are registered, as pending References
    And the held source is reported and left as it is, not registered again

  Scenario: Without cited-only every source the publication does not hold is taken in
    Given an earlier packet of seven sources, three cited, one of them already held as an accepted Reference
    When the packet's sources are taken in without the cited-only option
    Then the six sources not already held are registered
    And the accepted source is reported as existing and left accepted, not registered again

  Scenario: A publication's own corpus needs no entry in the repository's steering file
    When the corpus key "example" is resolved for the intake against the repository's steering file
    Then the corpus configuration is built from the backend's canonical corpus with no classifier

  Scenario: A corpus key that is neither listed nor the backend's own still fails
    When the corpus key "unknown-corpus" is resolved for the intake against the repository's steering file
    Then resolving it fails with "Unknown --corpus-key: unknown-corpus"

  Scenario: A failure in the intake after the packet is written is recorded, not raised
    Given the intake fails after the packet is written with "Unknown --corpus-key: ai-ml-research"
    When the multi-search run is made for the assignment
    Then the run does not stop with an error and its result says the intake failed with "Unknown --corpus-key: ai-ml-research"
    And the assignment records an intake failure event instead of a completed event

  Scenario: The direction is read from where an assignment really keeps it
    The API returns no metadata on the Assignment row; it lives in a ModelAttachment. A pack that reads only the row sends
    the reporter out with a title and no direction, so this is held against the stored shape.
    Given a Story with an assignment whose metadata is only in its attachment
    When the reporter pack is built for that assignment
    Then the pack's first layer has the editor's direction

  Scenario: A research run on a Story with no direction stops instead of searching blind
    Given a reporter assignment on a Story with no direction stored
    When its research run starts
    Then the run fails saying it needs the editor's direction
    And no search or model call was made

  # Every agent in a section works from the same context. An agent is a role and a list of layers, so a change to a shared layer reaches all of them.

  Scenario: Every agent working in a section reads the same section context
    When the context pack is built for each of the reporter, the copywriter and the editor on the Story
    Then the section's published Stories and accepted References are the same in all three packs
    And the publication's published Stories and accepted References are the same in all three packs

  Scenario: The copywriter's layers put the rules first and the publication's voice before the wider record
    When the copywriter's context pack is built for the Story
    Then the layers are, in order, "writing_guidelines, editorial_policies, byline, assignment, story, process, audience_lenses, story_references, related_references, story_conversation, prior_research, voice_examples, section_concepts, concept_references, desk_published, desk_references, publication_published, publication_references"
    And the system text says it is a copywriter and it writes a draft, never publishing

  Scenario: The copywriter reads the rules the draft will be checked against
    Given the site has a publication policy, a section policy of the same key that replaces it, and a disabled policy
    When the copywriter's context pack is built for the Story
    Then the editorial policies layer shows the section's wording and not the publication's
    And the editorial policies layer does not show the disabled policy

  Scenario: Research claims that did not pass stay marked for the copywriter
    When the copywriter's context pack is built for the Story
    Then the research layer is the one the reporter reads, which marks the claims that did not pass

  Scenario: Every agent is told where the Story is in the procedure
    When the context pack is built for each of the reporter, the copywriter and the editor on the Story
    Then each pack says what stage the Story is in, what is done and what is next
    When the editor's context pack is built for the section alone
    Then the pack holds no process layer

  Scenario: A copywriter keeps the research when the core does not fit, and gives up summaries first
    When the copywriter's context pack is built with a budget that only just fits the research
    Then the research is all there
    And the References lost their summaries

  Scenario: An outline is named as the editor's outline
    Given the Story's current version is marked as the editor's outline
    When the copywriter's context pack is built for the Story
    Then the Story layer shows the text as the editor's outline
    Given the Story's outline was marked on an earlier version
    When the copywriter's context pack is built for the Story
    Then the Story layer shows the text as a draft

  Scenario: Voice examples are whole published Stories, the section's first
    Given a published Story in the section and one in another section, both with their full text
    When the copywriter's context pack is built for the Story
    Then the voice examples show the section's Story in full before the other section's
    When the copywriter's context pack is built with a budget that has no room for a whole example
    Then no voice example is cut short
    And the voice examples layer reports what it dropped

  Scenario: With nothing published the pack says there is no example of the voice
    Given nothing is published
    When the copywriter's context pack is built for the Story
    Then the voice examples layer is empty and says nothing is published yet

  Scenario: An editor can work from a section before any Story exists
    Given the section has Stories in progress, a rated one older than an unrated one, a spiked one and a held one
    When the editor's context pack is built for the section alone
    Then the pack holds no Story layers
    And the pack names the section and no Story
    And the system text carries the role, the publication policy and the section mission
    And the Stories in progress show the rated one first, with its stars and stage
    And the Stories in progress do not show the spiked one or the held one
    And the Stories in progress do not show an idea nobody has picked
    And the section's published Stories and accepted References are shown

  Scenario Outline: What "recent" means is a setting, for the section and for the site separately
    Given Stories published in the section and in other sections over the last weeks
    When the editor's context pack is built for the section with recent published Stories in the section meaning <section> and in the site meaning <site>
    Then the section's published layer holds <in section> Stories
    And the site's published layer holds <in site> Stories
    And the pack records what recent meant

    Examples:
      | section   | site      | in section | in site |
      | 7 days    | 7 days    | 1          | 1       |
      | 30 days   | 7 days    | 3          | 1       |
      | 2 stories | 1 stories | 2          | 1       |

  Scenario: Without a setting the budget is the only bound on recent
    Given Stories published in the section and in other sections over the last weeks
    When the editor's context pack is built for the section alone
    Then the section's published layer holds 3 Stories
    And the site's published layer holds 2 Stories

  Scenario: A Story that has never been published is still found in its section
    Given the section has Stories in progress, a rated one older than an unrated one, a spiked one and a held one
    And none of them has a publication date
    When the editor's context pack is built for the section alone
    Then the Stories in progress show the rated one first, with its stars and stage

  Scenario: The section's in-progress list leaves out the Story the editor is working on
    Given the section has Stories in progress, a rated one older than an unrated one, a spiked one and a held one
    When the editor's context pack is built for the Story
    Then the Stories in progress do not show the Story itself

  Scenario Outline: A pack that does not make sense is refused, not guessed at
    When a context pack is asked for with <request>
    Then the pack is refused saying "<reason>"

    Examples:
      | request                       | reason                  |
      | the reporter and a section    | works on a Story        |
      | the copywriter and a section  | works on a Story        |
      | a Story and a section         | give one of them        |
      | neither a Story nor a section | give one of them        |
      | an unknown section            | Section not found       |

  # Guidelines as data (PPY-2a2a8a, PPY-de286b): a site's guidelines are an add-only layer after an agent's fixed role text, resolved for the Story's section.

  Scenario: The copywriter's pack holds the section's resolved writing guidelines after its role text
    Given the site has writing guidelines and the section "law-policy" adds to them
    When the copywriter's context pack is built for the Story
    Then the system text starts with the copywriter's role text
    And the writing guidelines layer comes first in the user text and holds the site's tone, then the section's tone, the audience, the words to avoid and the binding rule
    And the writing guidelines entry records the slug, the version and the content hash of each layer
    And the writing guidelines entry says which layer every field came from

  Scenario: The editor's pack holds only the voice, the audience and the binding rules
    Given the site has writing guidelines and the section "law-policy" adds to them
    When the editor's context pack is built for the Story
    Then the writing guidelines layer holds the voice, the audience and the binding rule
    And the writing guidelines layer does not hold the tone, the words to avoid or the guidelines' own prose

  Scenario: A site's guidelines cannot replace the fixed role text
    Given the site's writing guidelines try to replace the agent's instructions
    When the copywriter's context pack is built for the Story
    Then the system text is the same as for a site with no writing guidelines
    And the system text starts with the copywriter's role text
    And the attempt appears only inside the writing guidelines layer, after the role text

  Scenario: Writing guidelines are never shed when the pack is over budget
    Given the site has writing guidelines and the section "law-policy" adds to them
    When the copywriter's context pack is built with a budget of 10 characters
    Then the writing guidelines layer is complete and reports nothing dropped
    When the copywriter's context pack is built with a budget that only just fits the research
    Then the writing guidelines layer is complete and reports nothing dropped

  Scenario: A pack built for a site with no writing guidelines carries the missing warning
    When the copywriter's context pack is built for the Story
    Then the writing guidelines layer is empty and says the publication has no writing guidelines
    And the warnings say the writing guidelines are missing, and nothing is invented

  Scenario: The voice examples start with the exemplars the section's guidelines name
    Given the site has writing guidelines and the section "law-policy" adds to them
    And a published Story in the section and one in another section, both with their full text
    And the section's writing guidelines name the other section's Story as an exemplar
    When the copywriter's context pack is built for the Story
    Then the voice examples show the exemplar first, with the editors' note, and the section's Story after it
    And no Story appears twice in the voice examples

  Scenario: The illustrator's image style uses the section's own image guidelines
    Given the site has an image style and the section "law-policy" has its own image guidelines
    When the illustrator's context pack is built for the Story
    Then the visual style layer shows the section's guidance
    And the visual style entry records the version and hash of both the publication's and the section's image guidelines

  Scenario: Role texts name no publication
    Then the role texts in the context pack hold no publication-specific wording
    And the lint fails on a role text that names a site

  # The byline policy (PPY-804b7b): who a story may be credited to is the site's rule, with the honest rule as the default.
  Scenario: A site with no byline policy gets the honest rule
    When the copywriter's context pack is built for the Story
    Then the byline layer says to attribute agent work to AI and never invent an author
    And the byline layer says it is the default

  Scenario: A satire site publishes under its own pen names
    Given the site's byline policy is pen names "Chip Hardcastle" and "Dolores Finch"
    When the copywriter's context pack is built for the Story
    Then the byline layer lists the pen names "Chip Hardcastle" and "Dolores Finch"
    And the byline layer says it came from the site
    And the byline layer does not tell the writer to attribute the work to AI

  Scenario: A pen-names policy with no pen names is refused when saved
    When an admin saves a pen-names byline policy with no pen names
    Then the save is refused because a pen-names policy needs at least one pen name

  Scenario: Only the publication has a byline policy
    When an admin saves a byline policy for the section "law-policy"
    Then the save is refused because the byline rules belong to the publication

  Scenario: A byline policy that cannot be read stops the pack rather than telling the writer the default
    Given the site's byline policy is pen names "Chip Hardcastle" and "Dolores Finch"
    And the site's byline policy document cannot be read
    When the copywriter's context pack build is attempted
    Then the attempt fails saying the document could not be read
