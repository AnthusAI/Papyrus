Feature: One definition of the four lenses a Story is reviewed through
  Before a Story is published it is looked at four ways: as people read it, as AI reader agents read it, as search crawlers read it
  and as a social preview shows it. The four lenses are defined once, in src/papyrus_content/audience_lenses.py, in the way the Story
  procedure is defined once. Each lens has a checklist step, an audience, a paragraph on what good looks like and a list of checks.
  Each check says how it is made (by code, by the decision model, by the writing model or by a person), how serious a failure is by
  default, what evidence it shows and which agent roles can satisfy it while they work. The documentation table, the section of every
  agent's context pack and the lens lines of papyrus stories next are all generated from that one definition, so there is no second copy.
  The lens steps are mainly for agents to do before a person reviews the Story, so obvious problems are fixed before human time is spent.
  An agent may finish a lens step and is recorded by name; only a person gives the final approval. Three failures are errors, which means
  a step cannot be closed as done while they stand: an image with no alt text, a third-party image with no credit, and a Markdown copy
  that differs from the Story's source. Nothing here calls a model, and no lens adds a gate to publishing: the checklist's own open-step
  rule is the gate.

  Scenario: The four lenses name the four checklist steps
    Then the lenses are, in order, "people, agents, search, social"
    And their steps are "review_people, review_reader_agents, review_search, review_social"

  Scenario: Every check says how it is made and how serious a failure is
    Then every check has a method of code, the decision model, the writing model or a person
    And every check made by code, the decision model or the writing model has a severity of info, warn or error
    And every check made by the decision model has a question

  Scenario: Exactly three failures are errors
    Then the checks whose default severity is error are "P7, P10, A2, C6"
    And the checks P10 and C6 report the same fact and mirror each other

  Scenario: The documentation table is the definition and nothing else
    Then the table in docs/four-lens-review.md is exactly the one generated from the definition
    And the table has a row for every check

  Scenario: Every agent reads the lenses in its context pack
    Given a newsroom with a publication policy, a section "law-policy" and a Story "story-1" in it
    When the context pack is built for each of the reporter, the copywriter and the editor on the Story
    Then each pack has an audience lenses layer
    And no pack left the audience lenses layer out when it was short of room

  Scenario: Each role reads only the checks it can satisfy
    Given a newsroom with a publication policy, a section "law-policy" and a Story "story-1" in it
    When the context pack is built for each of the reporter, the copywriter and the editor on the Story
    Then the copywriter's lens text names "Every image has alt text"
    And the editor's lens text names "Every image has alt text"
    And the reporter's lens text does not name "Every image has alt text"
    And the reporter's lens text names "Every third-party image is credited"
    And the reporter's lens text names "Each outside claim cites a Reference"

  Scenario: Agents are told they may finish a lens step and a person approves
    Given a newsroom with a publication policy, a section "law-policy" and a Story "story-1" in it
    When the copywriter's context pack is built for the Story
    Then the lens text says an agent may complete a lens step
    And the lens text says only a person gives the final approval
    And the lens text names the three problems that must be fixed before a step can close

  Scenario: The copywriter is told accuracy and natural writing beat any lens
    Given a newsroom with a publication policy, a section "law-policy" and a Story "story-1" in it
    When the copywriter's context pack is built for the Story
    Then the system text tells the copywriter never to stuff keywords or write a misleading teaser
    And the lens text says accuracy and natural writing beat every lens

  Scenario: A site that adds no policy of its own still reads the defaults
    Given a newsroom with a publication policy, a section "law-policy" and a Story "story-1" in it
    When the copywriter's context pack is built for the Story
    Then the lens text names all four lenses

  Scenario: A section alone has no Story to review, so its pack has no lens layer
    Given a newsroom with a publication policy, a section "law-policy" and a Story "story-1" in it
    When the editor's context pack is built for the section alone
    Then the pack holds no audience lenses layer

  Scenario: Stories next shows a lens line for each lens step that is not done
    Given a Story at the "copywriting" stage
    When I run "stories next" with "--story story-1"
    Then the procedure output has a lens line for each of the four steps
    And each lens line says it is not checked yet
    And the procedure command wrote no records

  Scenario: Stories next in JSON carries the lenses
    Given a Story at the "copywriting" stage
    When I run "stories next" with "--story story-1 --json"
    Then the JSON result lists the four lenses with their audiences

  Scenario: A lens step the checklist records as done is not listed again
    Given a Story at the "copywriting" stage
    And the checklist records the step "review_people" as done
    When I run "stories next" with "--story story-1"
    Then the procedure output has no lens line for "review_people"
    And the procedure output has a lens line for "review_search"
