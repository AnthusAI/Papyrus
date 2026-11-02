Feature: An idea is more than a summary of its Reference
  The ideas a site proposes are for its editors to decide on, and an idea that only restates its source tells them nothing the source does not. A reader can
  read the source. So an idea is filed only when it says something its sources do not. That takes two things. First, it rests on something the newsroom
  already knows about the Reference beyond the source itself: the words an editor wrote when they accepted it, a comment someone made about it, or another
  accepted Reference linked to it (a link people confirmed, or a close match as close as the site's typical nearest neighbour), together with the words an
  editor wrote on that link. Themes and trends are means to such a connection, never a requirement of it. The writer is shown these as handles it must cite
  beside the source, as direction for what to look for: the editors' words are never reported in the story and never ground a fact, and the story never
  describes how it came to be (who accepted what, what was suggested, what was matched by similarity). The rules that follow its answer are deterministic: the
  dek and at least one body sentence rest on a connection, the connecting sentence shares a content word with what it cites, a comment is never evidence alone,
  and no trend is claimed because no counts are given. Second, a model that is told nothing about how the draft was written reads the draft against its sources
  and says whether it makes a claim of its own that they do not make. It fails closed: a draft that restates its sources, makes a claim they do not support,
  repeats itself or talks about its own process is not filed, and neither is a draft whose check gave no usable answer. A writer that has no point to make is
  not checked at all.
  A Reference with nothing to connect to is skipped before the model is asked, is not marked drafted, and is looked at again on the next run, when an
  accept reason, a comment or a link may exist. An editor's accept reason is enough for a Reference whose page was read, but a Reference whose page could not
  be read (no page text and no real summary) needs a comment or a related Reference as well: an idea must never describe what it cannot read.
  A Reference whose draft was rejected is not written again on every run, which would cost money and could starve the others. The run remembers what was
  rejected and against which connections, and writes the Reference again only when a connection appears that the rejection was not made against: a new
  comment, a new accept reason, a new related Reference, a suggested link that an editor confirms, or a new explanation on a link. There is no count and no
  waiting period; a connection that goes away is not news and one that comes back is not new. A check that failed to answer says nothing about the Reference
  and is not remembered. A small site proposes fewer ideas and the bar is not lowered for it; an empty run is correct, and when a run files nothing for want of
  a connection or because its drafts added nothing, it raises one flag in the Notification Center that says what would help. There is one standard: a site's
  old `minimumStandard` setting is retired, still loads, and is ignored.

  Scenario: An idea whose every sentence rests on the source alone is not filed
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story whose every sentence cites only the source
    When the run drafts ideas
    Then the run files no idea
    And the run record says the draft failed with "dek_without_connection" and "only_the_source_cited"

  Scenario: The editors' accept reason is offered to the writer as direction and the idea is checked for a point of its own
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story that rests on the editors' reason
    When the run drafts ideas
    Then the run files 1 idea
    And the model was shown the editors' reason marked as direction and not as a fact
    And the idea records the connections "acceptReason"
    And the idea body quotes the editors' reason apart from its sources
    And the run record counts 1 idea resting on "acceptReason"
    And the point check was asked once about the idea and found that it adds something

  Scenario: A sentence that tells how the story came to be is not filed
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story that reports why the editors accepted the item
    When the run drafts ideas
    Then the run files no idea
    And the run record says the draft failed with "internal_wording"

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

  Scenario Outline: A draft that says nothing its sources do not is not filed, and the run records the reason
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story that rests on the editors' reason
    And the point check answers that the draft <answer>
    When the run drafts ideas
    Then the run files no idea
    And the run record says the draft failed with "<reason>"
    And the point check's verdict and the draft's sentences are in the run record
    And one flag is open in the Notification Center

    Examples:
      | answer                                           | reason                 |
      | restates its source                              | no_point_beyond_source |
      | claims something its sources do not support      | point_unsupported      |
      | repeats itself                                   | repeats_itself         |
      | talks about how the story came to be             | exposes_process        |

  Scenario: A draft whose point check gave no usable answer is not filed and is not remembered as rejected
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story that rests on the editors' reason
    And the point check gives no usable answer
    When the run drafts ideas
    Then the run files no idea
    And the run record says the draft failed with "point_check_error"
    And nothing is remembered about "A tool that checks claims"
    When the point check answers that the draft adds something
    And the run drafts ideas
    Then the run files 1 idea

  Scenario: A writer that has no point to make is not checked and its Reference is remembered as rejected
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story with no point
    When the run drafts ideas
    Then the run files no idea
    And "A tool that checks claims" is skipped as "no_point_offered"
    And the point check was not asked
    And "A tool that checks claims" is remembered as rejected for "no_point_offered"

  Scenario: A Reference whose draft was rejected is not written again until the newsroom knows something new about it
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story that rests on the editors' reason
    And the point check answers that the draft restates its source
    When the run drafts ideas
    Then the run files no idea
    And "A tool that checks claims" is remembered as rejected for "point_check_failed" against the accept reason
    When the point check answers that the draft adds something
    And the run drafts ideas
    Then the model was asked nothing in that run
    And "A tool that checks claims" is skipped as "already_rejected"
    And the run files no idea
    And one flag is open in the Notification Center

  Scenario Outline: Each kind of new connection makes a rejected Reference worth another try
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And the model writes a story that rests on the editors' reason
    And the point check answers that the draft restates its source
    And the run considers "A tool that checks claims" only
    When the run drafts ideas
    Then the run files no idea
    When the point check answers that the draft adds something
    And <change>
    And the run drafts ideas
    Then the run files 1 idea
    And the run record says "A tool that checks claims" was tried again because of <connection>

    Examples:
      | change                                                                                                   | connection                  |
      | an editor commented on "A tool that checks claims": "Claim checking is overdue for us."                  | a new comment               |
      | an editor accepts "A tool that checks claims" again and writes "A new reason: claim checking in sourcing." | a new accept reason         |
      | editors linked "A tool that checks claims" to "A tool that checks quotations"                            | a new confirmed link        |
      | editors connected "A tool that checks claims" to "A tool that checks quotations" and explained "Both check claims." | a new link and explanation |

  Scenario: A suggested link that an editor confirms is new, and a connection that goes away and comes back is not
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the summary "A tool that checks quotations against archives."
    And the vector index suggests these matches:
      | first                     | second                        | similarity |
      | A tool that checks claims | A tool that checks quotations | 0.90       |
    And the model writes a story that rests on the editors' reason
    And the point check answers that the draft restates its source
    And the run considers "A tool that checks claims" only
    When the run drafts ideas
    And editors confirm the link between "A tool that checks claims" and "A tool that checks quotations"
    And the run drafts ideas
    Then the run record says "A tool that checks claims" was tried again because of a new confirmed link
    When the link between "A tool that checks claims" and "A tool that checks quotations" goes away
    And the run drafts ideas
    Then "A tool that checks claims" is skipped as "already_rejected"
    When the link between "A tool that checks claims" and "A tool that checks quotations" comes back
    And the run drafts ideas
    Then "A tool that checks claims" is skipped as "already_rejected"

  Scenario: A rejected Reference does not take the attempt that another Reference needs
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the accepted Reference "A tool that checks quotations" with the editors' reason "Claim checking matters to our sourcing coverage."
    And "A tool that checks claims" was rejected before and nothing new is known about it
    And the model writes a story that rests on the editors' reason
    When the run drafts ideas with room for 1 attempt
    Then the run files 1 idea
    And the idea targets "A tool that checks quotations"

  Scenario: A dry run reads the memory and writes nothing to it
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story that rests on the editors' reason
    And the point check answers that the draft restates its source
    When the run drafts ideas as a dry run
    Then nothing is remembered about "A tool that checks claims"

  Scenario: A memory that cannot be read or written does not stop the run
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story that rests on the editors' reason
    And the memory of rejections is unavailable
    When the run drafts ideas
    Then the run files 1 idea
    And the run record names the memory as unavailable

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

  Scenario: A story about what an unreadable page contains is not filed, even with a comment to go on
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the page of "A tool that checks claims" cannot be read and the monitor stored no summary
    And an editor commented on "A tool that checks claims": "Claim checking is overdue for us."
    And the model writes a story that describes what the page contains
    When the run drafts ideas
    Then the run files no idea
    And the run record says the draft failed with "describes_unread_page"

  Scenario: A comment on a Reference whose page could not be read lets an idea be written about how the comment bears on it, not about what the page says
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the page of "A tool that checks claims" cannot be read and the monitor stored no summary
    And an editor commented on "A tool that checks claims": "Claim checking is overdue for us."
    And the model writes a story that rests on the comment and the editors' reason
    When the run drafts ideas
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

  Scenario: A run that files nothing because its drafts added nothing asks editors to curate, and says it is waiting for something new
    Given the accepted Reference "A tool that checks claims" with the editors' reason "Claim checking matters to our sourcing coverage."
    And the model writes a story that rests on the editors' reason
    And the point check answers that the draft restates its source
    When the run drafts ideas
    Then one flag is open in the Notification Center
    And the flag says "No ideas today: 1 idea would have said no more than its sources, so the ideas would only have summarised them."
    And the flag says a rejected idea is written again as soon as there is something new to connect it to

  Scenario: A site's old minimum standard setting still loads and is ignored
    Then a stored config with the retired setting "minimumStandard" still loads
    And its value, whatever it was, changes nothing
    And an unknown setting is still refused
