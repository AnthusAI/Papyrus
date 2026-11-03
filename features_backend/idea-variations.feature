Feature: An idea run offers different ways to connect the same item to what the newsroom knows
  A new item could connect to the newsroom's existing knowledge in more than one way: to another accepted Reference, to another Story, to a concept (including a
  hashtag an editor typed). When a run files an idea it also offers those as variations of the idea, so an editor sees the options side by side and chooses
  one, instead of getting only the angle the writer happened to pick. Variation 1 is always the idea as filed. Every other connection the idea does not
  already rest on gets at most one more variation, with its own point, headline, dek and body, its connections and the verdict of the point check. A
  variation is offered only if it passes everything the idea passed: the citation rules, the rules that make it more than a summary, and the point check.
  The count is not fixed. A Reference with few connections gets one variation or two, a writer with nothing to say about a connection offers nothing for it,
  and no connection is used twice, so there is no made-up variety. What the variations cost is visible in the run record, counts against the run's cost limit
  and is part of the run's total. Nothing here can cost the idea: it is filed first, a failure to offer variations is recorded in the run, and the same
  failure twice in a row turns the offering off for the rest of the run instead of paying for variations that cannot be kept. A Story that already has
  generated variations is left alone, so a rerun adds nothing. The model is the run's own (gpt-6-luna).

  Scenario: An idea is its own first variation, and a Reference with no other connection gets only that one
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story that rests on the editors' reason
    When the run drafts ideas
    Then the run files 1 idea
    And the idea has 1 variation
    And offered variation 1 is the idea as filed
    And offered variation 1 connects to the Reference "A tool that checks claims" itself
    And offered variation 1 records that the point check found it adds something
    And no model was asked to write other versions

  Scenario: A related Reference gives a second variation with a point of its own
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And editors linked "A tool that checks claims" to "A tool that checks quotations"
    And the model writes a story that rests on the editors' reason
    And the model writes a version for the related Reference
    When the run drafts ideas for "A tool that checks claims" only
    Then the idea has 2 variations
    And offered variation 1 is the idea as filed
    And offered variation 2 has the point "Quotation checking covers what claim checking alone leaves open."
    And offered variation 2 connects to the "reference" "A tool that checks quotations"
    And offered variation 2 records that the point check found it adds something
    And the model was shown the related Reference as an option

  Scenario: Another Story the newsroom has gives a variation that connects to that Story
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And editors linked "A tool that checks claims" to "A tool that checks quotations"
    And the Story "How archives keep quotations honest" rests on "A tool that checks quotations"
    And the model writes a story that rests on the editors' reason
    And the model writes a version for the other Story
    When the run drafts ideas for "A tool that checks claims" only
    Then offered variation 2 connects to the "story" "How archives keep quotations honest"
    And the model was shown the other Story as an option

  Scenario: A Story that is still an idea, or was declined, is not something to connect to
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And editors linked "A tool that checks claims" to "A tool that checks quotations"
    And the idea "An earlier idea about archives" rests on "A tool that checks quotations"
    And the model writes a story that rests on the editors' reason
    When the run drafts ideas for "A tool that checks claims" only
    Then the idea has 1 variation
    And the model was shown no Story as an option

  Scenario: A concept an editor typed as a hashtag gives a variation that connects to the concept
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And an editor tagged "A tool that checks claims" with the concept "#source-audits" described as "Work that audits where a claim came from."
    And the model writes a story that rests on the editors' reason
    And the model writes a version for the concept
    When the run drafts ideas
    Then the idea has 2 variations
    And offered variation 2 connects to the "concept" "#source-audits"
    And the model was shown the concept as an option

  Scenario: Each distinct connection gets its own variation, in the order they were offered
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And editors linked "A tool that checks claims" to "A tool that checks quotations"
    And the Story "How archives keep quotations honest" rests on "A tool that checks quotations"
    And an editor tagged "A tool that checks claims" with the concept "#source-audits" described as "Work that audits where a claim came from."
    And the model writes a story that rests on the editors' reason
    And the model writes a version for the related Reference
    And the model writes a version for the other Story
    And the model writes a version for the concept
    When the run drafts ideas for "A tool that checks claims" only
    Then the idea has 4 variations
    And the variations connect, in order, to a "reference", a "reference", a "story" and a "concept"
    And the writer was asked once for all three other versions

  Scenario: A connection the writer has no point for gets nothing
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And an editor tagged "A tool that checks claims" with the concept "#source-audits" described as "Work that audits where a claim came from."
    And the model writes a story that rests on the editors' reason
    And the model has no point for the concept
    When the run drafts ideas
    Then the idea has 1 variation
    And the run record says nothing was offered for "C1" because the writer offered no point

  Scenario: A version that only restates its source is not offered, and the others still are
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And editors linked "A tool that checks claims" to "A tool that checks quotations"
    And an editor tagged "A tool that checks claims" with the concept "#source-audits" described as "Work that audits where a claim came from."
    And the model writes a story that rests on the editors' reason
    And the model writes a version for the related Reference
    And the model writes a version for the concept
    And the point check answers that the version for the related Reference restates its source
    When the run drafts ideas for "A tool that checks claims" only
    Then the idea has 2 variations
    And offered variation 2 connects to the "concept" "#source-audits"
    And the run record says nothing was offered for "R1" because the point check failed with "no_point_beyond_source"

  Scenario: A version that does not rest on its own connection is not offered
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And editors linked "A tool that checks claims" to "A tool that checks quotations"
    And the model writes a story that rests on the editors' reason
    And the model writes a version for the related Reference that cites only the source
    When the run drafts ideas for "A tool that checks claims" only
    Then the idea has 1 variation
    And the run record says nothing was offered for "R1" because the citation check failed

  Scenario: A version that repeats the idea's headline is not a different angle
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And editors linked "A tool that checks claims" to "A tool that checks quotations"
    And the model writes a story that rests on the editors' reason
    And the model writes a version for the related Reference that repeats the idea's headline
    When the run drafts ideas for "A tool that checks claims" only
    Then the idea has 1 variation
    And the run record says nothing was offered for "R1" because it repeats another variation

  Scenario: What the variations cost is in the run record and in the run's total
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And editors linked "A tool that checks claims" to "A tool that checks quotations"
    And the model writes a story that rests on the editors' reason
    And the model writes a version for the related Reference
    When the run drafts ideas for "A tool that checks claims" only
    Then the run record shows 2 model calls for variations at a cost
    And the run's total counts the 4 model calls: the idea, its check, the other versions and their check

  Scenario: The run's cost limit holds the variations back and keeps the idea
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And editors linked "A tool that checks claims" to "A tool that checks quotations"
    And the model writes a story that rests on the editors' reason
    And the model writes a version for the related Reference
    When the run drafts ideas for "A tool that checks claims" only with only enough budget for the idea
    Then the run files 1 idea
    And the idea has 1 variation
    And the run record says the other versions were held back by the cost limit

  Scenario: A dry run asks and checks but writes nothing
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And editors linked "A tool that checks claims" to "A tool that checks quotations"
    And the model writes a story that rests on the editors' reason
    And the model writes a version for the related Reference
    When the run drafts ideas as a dry run
    Then no variation was written
    And the run record lists 2 variations that would have been offered

  Scenario: Offering the variations of a Story twice adds nothing
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And editors linked "A tool that checks claims" to "A tool that checks quotations"
    And the model writes a story that rests on the editors' reason
    And the model writes a version for the related Reference
    And the run drafts ideas for "A tool that checks claims" only
    When the variations of that idea are offered again
    Then the idea has 2 variations
    And the writer was asked once for the other versions

  Scenario: A failure to offer variations never costs the idea, and the same failure twice turns the offering off
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the editors' reason "Quotation checking matters to our sourcing coverage."
    And the backend refuses to create variations
    And the model writes a different story for each Reference
    When the run drafts ideas
    Then the run files 2 ideas
    And the run record has 2 variation errors and says the offering was turned off
    And no model was asked to write other versions

  Scenario: Variations are written and read on a backend whose records carry a tenant
    Given a backend for the tenant "machines-on-machines"
    When a run offers 2 variations of a Story to that backend
    Then the backend holds 2 variations of the Story without a tenant column
    And an authoring client of that tenant reads both back in order
