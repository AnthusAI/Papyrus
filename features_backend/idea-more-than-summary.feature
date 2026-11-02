Feature: An idea is more than a summary of its Reference
  The ideas a site proposes are for its editors to decide on, and an idea that only restates its source tells them nothing the source does not. A reader can
  read the source. So an idea is filed only when it rests on something the newsroom already knows about the Reference beyond the source itself: the words
  an editor wrote when they accepted it, a comment someone made about it, or another accepted Reference linked to it (a link people confirmed, or a close
  match as close as the site's typical nearest neighbour), together with the words an editor wrote on that link. Themes and trends are means to such a
  connection, never a requirement of it. The writer is shown these as handles it must cite beside the source, and the rules that follow its answer are
  deterministic: the dek and at least one body sentence rest on a connection, the connecting sentence shares a content word with what it cites, the
  editors' words are reported as the editors' view and never as a fact, a message is never evidence alone, and no trend is claimed because no counts are given.
  A Reference with nothing to connect to is skipped before the model is asked, is not marked drafted, and is looked at again on the next run, when an
  accept reason, a comment or a link may exist. An editor's accept reason is enough for a Reference whose page was read, but a Reference whose page could not
  be read (no page text and no real summary) needs a comment or a related Reference as well: an idea must never describe what it cannot read. A small site
  proposes fewer ideas; an empty run is correct, and when a run files nothing for want of a connection it raises one flag in the Notification Center that says
  what would help. A site's setting `minimumStandard` is `more-than-summary` unless it says `summary`, the old behaviour kept only so the two can be compared.

  Background:
    Given a site that holds its ideas to the minimum standard "more-than-summary"

  Scenario: An idea whose every sentence rests on the source alone is not filed
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story whose every sentence cites only the source
    When the run drafts ideas
    Then the run files no idea
    And the run record says the draft failed with "dek_without_connection" and "only_the_source_cited"

  Scenario: The editors' accept reason is offered to the writer and cited as their view, never as a fact
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story that rests on the editors' reason
    When the run drafts ideas
    Then the run files 1 idea
    And the model was shown the editors' reason marked as their view and not as a fact
    And the idea records the connections "acceptReason"
    And the idea body quotes the editors' reason apart from its sources
    And the run record counts 1 idea resting on "acceptReason"

  Scenario: A sentence that reports the editors' reason without saying it is the editors' view is not filed
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story that states the editors' reason as a fact
    When the run drafts ideas
    Then the run files no idea
    And the run record says the draft failed with "editors_view_not_attributed"

  Scenario: A connecting sentence that shares no word with what it cites is not filed
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story whose connecting sentence is about something else
    When the run drafts ideas
    Then the run files no idea
    And the run record says the draft failed with "connection_ungrounded"

  Scenario: An idea cannot claim a trend because it is given no counts
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story that calls claim checking a trend
    When the run drafts ideas
    Then the run files no idea
    And the run record says the draft failed with "trend_claim_without_signal"

  Scenario: A Reference with nothing to connect to is skipped before the model is asked and looked at again on the next run
    Given the accepted Reference "A tool that checks claims" that no editor has said anything about
    When the run drafts ideas
    Then the model is asked 0 times
    And "A tool that checks claims" is skipped as "nothing_to_add"
    And the run files no idea
    When an editor accepts "A tool that checks claims" again and writes "Claim checking matters to our sourcing coverage."
    And the model writes a story that rests on the editors' reason
    And the run drafts ideas
    Then the run files 1 idea

  Scenario: An accept reason alone does not clear the bar for a Reference whose page could not be read
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the page of "A tool that checks claims" cannot be read and the monitor stored no summary
    When the run drafts ideas
    Then the model is asked 0 times
    And "A tool that checks claims" is skipped as "nothing_to_add"

  Scenario: A comment on a Reference whose page could not be read lets an idea be written about how the comment bears on it, not about what the page says
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the page of "A tool that checks claims" cannot be read and the monitor stored no summary
    And an editor commented on "A tool that checks claims": "Claim checking is overdue for us."
    And the model writes a story that describes what the page contains
    When the run drafts ideas
    Then the run files no idea
    And the run record says the draft failed with "describes_unread_page"
    When the model writes a story that rests on the comment and the editors' reason
    And the run drafts ideas
    Then the run files 1 idea
    And the idea records the connections "acceptReason" and "message:M1"

  Scenario: A related Reference lets an idea be written about a Reference whose page could not be read
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And the page of "A tool that checks claims" cannot be read and the monitor stored no summary
    And editors linked "A tool that checks claims" to "A tool that checks quotations"
    And the model writes a story that rests on the related Reference
    When the run drafts ideas for "A tool that checks claims" only
    Then the run files 1 idea
    And the idea records the connections "acceptReason" and "neighbour:R1"
    And the idea still targets only "A tool that checks claims"

  Scenario: The words an editor wrote on a link count as a connection of their own, and the rule does not need them
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And editors connected "A tool that checks claims" to "A tool that checks quotations" and explained "Both guard the newsroom's sourcing."
    When the connections of "A tool that checks claims" are read
    Then the connections are "E1", "R1" and "X1"
    And "X1" carries the editors' explanation "Both guard the newsroom's sourcing." as the editors' view
    When the build has no editors' explanations on its links
    And the connections of "A tool that checks claims" are read
    Then the connections are "E1" and "R1"

  Scenario: A close match counts as a related Reference only at the site's typical nearest-neighbour similarity
    Given four accepted References "Alpha", "Beta", "Gamma" and "Delta" each with a summary
    And the vector index suggests these matches:
      | first | second | similarity |
      | Alpha | Beta   | 0.90       |
      | Alpha | Gamma  | 0.60       |
      | Gamma | Delta  | 0.70       |
    When the connections of "Alpha" are read
    Then the related References are "Beta"
    And the site's typical nearest-neighbour similarity is 0.80

  Scenario: A related Reference with only a title is not something to write from
    Given the accepted Reference "Alpha" with no summary
    And the accepted Reference "Beta" with no summary
    And the vector index suggests these matches:
      | first | second | similarity |
      | Alpha | Beta   | 0.90       |
    When the connections of "Alpha" are read
    Then there are no related References

  Scenario: A run that files nothing for want of a connection raises one flag that says what would help
    Given the accepted Reference "A tool that checks claims" that no editor has said anything about
    And the accepted Reference "A tool that checks quotations" that no editor has said anything about
    And the vector index suggests these matches:
      | first                    | second                        | similarity |
      | A tool that checks claims | A tool that checks quotations | 0.40       |
    When the run drafts ideas
    Then one flag is open in the Notification Center
    And the flag says "No ideas today: 2 accepted References had nothing to connect to, so the ideas would only have summarised them."
    And the flag asks editors to add a reason when they accept, to confirm the suggested links waiting in Related and to comment, and names the waiting titles
    And the flag does not use the words "Draft" or "desk"

  Scenario: An open flag is not raised twice
    Given the accepted Reference "A tool that checks claims" that no editor has said anything about
    When the run drafts ideas
    And the run drafts ideas
    Then one flag is open in the Notification Center

  Scenario: A run that files ideas acknowledges the open flag
    Given the accepted Reference "A tool that checks claims" that no editor has said anything about
    When the run drafts ideas
    And an editor accepts "A tool that checks claims" again and writes "Claim checking matters to our sourcing coverage."
    And the model writes a story that rests on the editors' reason
    And the run drafts ideas
    Then the run files 1 idea
    And the flag is acknowledged because ideas are flowing again

  Scenario: When there is nothing accepted to write about the flag asks for accepted References
    Given a pending Reference "Waiting"
    When the run drafts ideas
    Then one flag is open in the Notification Center
    And the flag says "No ideas today: no accepted References are waiting to be written about."

  Scenario: A dry run raises no flag and the Reference is not marked drafted
    Given the accepted Reference "A tool that checks claims" that no editor has said anything about
    When the run drafts ideas as a dry run
    Then no flag is raised
    And the run files nothing

  Scenario: The old standard still files a summary, so the two can be compared
    Given a site that holds its ideas to the minimum standard "summary"
    And the accepted Reference "A tool that checks claims" that no editor has said anything about
    And the model writes a story whose every sentence cites only the source
    When the run drafts ideas
    Then the run files 1 idea
    And the model was not shown what the newsroom knows
    And no flag is raised

  Scenario: A site's minimum standard is a setting with one default
    Then a site that says nothing about its minimum standard has "more-than-summary"
    And a site may say "summary"
    And any other minimum standard is refused
