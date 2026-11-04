Feature: Everything a model writes from sources is fact checked, in layers, before anyone relies on it
  A model that is told to use only its sources still invents. A research packet once named a man "Rodney Reid" where the source said
  only "Reid", and called a man a Tennessee resident where the source said he lived somewhere else. A rule in the prompt does not stop
  that, so the shared fact check (contract fact-check/v1) reads every claim against the text of the sources it cites. The first layer
  is plain code. Every name, number, date, place and quotation in a claim must appear in the cited sources, and code does not forgive
  a missing one. The second layer is an independent judge: a separate model call that is told nothing about how the claim was written
  and must answer with quotes taken word for word from the source, one for each part of the claim, which code then looks for. A claim is verified only when the
  literal check passes, the judge says the source supports it with quotes that all really are there, and the claim does not present as
  fact something the source only attributes to a party. A failed judge never counts as a pass: the claim is unchecked. The judge
  cannot rescue a claim that failed the literal check. The check also reports how many independent domains stand behind each claim,
  and that never fails a claim. In a multi-search research packet, a claim that is not verified is never deleted and never passed on
  as fact: it is held in a list of unverified claims with the reasons, the summary is written again from the verified claims alone,
  sources only a failed claim cited are not taken in as References, and a later reporter sees the failed claims labelled.

  Scenario: A name the sources only half give fails the literal check
    Given the source "s1" says "Councilor Marlow said the plan would cost the town more each year."
    And a claim "Councilor Ada Marlow said the plan would cost the town more each year." citing "s1"
    When the claims are fact checked without a judge
    Then the claim is "not_shown" because of unmatched terms "Ada"

  Scenario: A place the sources never mention fails the literal check
    Given the source "s1" says "Alder Vance, who lives in Brightwater, was held for a year."
    And a claim "Ohio resident Alder Vance was held for a year." citing "s1"
    When the claims are fact checked without a judge
    Then the claim is "not_shown" because of unmatched terms "Ohio"

  Scenario: Numbers match however they are written
    Given the source "s1" says "The town agreed to pay 200,000 dollars. Its 2024 budget was $2.5 million, up 12 percent. Fifteen homes flooded."
    And a claim "The town paid $200,000 from a 2024 budget of $2.5 million, up 12%, and 15 homes flooded." citing "s1"
    When the claims are fact checked without a judge
    Then the claim has no unmatched terms

  Scenario: A number the sources do not give fails the literal check
    Given the source "s1" says "The town agreed to pay $200,000."
    And a claim "The town agreed to pay $250,000." citing "s1"
    When the claims are fact checked without a judge
    Then the claim is "not_shown" because of unmatched terms "250,000"

  Scenario: A quotation must appear in the sources, however the quotation marks are typed
    Given the source "s1" says "She called it “a plain mistake” on Tuesday."
    And a claim 'She called it "a plain mistake".' citing "s1"
    And a claim 'She called it "a grave error".' citing "s1"
    When the claims are fact checked without a judge
    Then claim 1 has no unmatched terms
    And claim 2 is "not_shown" because of unmatched terms "a grave error"

  Scenario: Without a judge a claim that passes the literal check is unchecked, never verified
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "Councilor Marlow spoke on Tuesday." citing "s1"
    When the claims are fact checked without a judge
    Then the claim comes out "unchecked"

  Scenario: A supportive judge with a real quote verifies a claim
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "Councilor Marlow spoke on Tuesday." citing "s1"
    And the judge says "supported" quoting "Councilor Marlow spoke on Tuesday."
    When the claims are fact checked
    Then the claim comes out "verified"

  Scenario: A judge quote that is not in the source demotes the claim
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "Councilor Marlow spoke on Tuesday." citing "s1"
    And the judge says "supported" quoting "Councilor Marlow spoke at length on Tuesday night."
    When the claims are fact checked
    Then the claim is "not_shown" because of "quote_not_in_source"
    And the judge verdict recorded for the claim is "not_supported"

  Scenario: A judge that fails leaves the claim unchecked and the others still checked
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "Councilor Marlow spoke on Tuesday." citing "s1"
    And a claim "Councilor Marlow spoke." citing "s1"
    And the judge fails on the claim "Councilor Marlow spoke on Tuesday." and supports the others quoting "Councilor Marlow spoke"
    When the claims are fact checked
    Then claim 1 comes out "unchecked"
    And claim 2 comes out "verified"
    And the counts are 1 verified, 0 needs_check, 0 contradicted, 0 not_shown, 1 unchecked

  Scenario: A literal failure cannot be overridden by a supportive judge
    Given the source "s1" says "Alder Vance was held for a year."
    And a claim "Ohio resident Alder Vance was held for a year." citing "s1"
    And the judge says "supported" quoting "Alder Vance was held for a year."
    When the claims are fact checked
    Then the claim is "not_shown" because of unmatched terms "Ohio"

  Scenario: An allegation stated as fact needs a check even when the judge finds it supported
    Given the source "s1" says "The complaint alleges that the officer ignored the witness."
    And a claim "The officer ignored the witness." citing "s1"
    And the judge says "supported" quoting "the officer ignored the witness" and reports the attribution lost
    When the claims are fact checked
    Then the claim is "needs_check" because of "attribution_lost"

  Scenario: A judge that says the source is silent rejects the claim
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "Councilor Marlow spoke on Tuesday." citing "s1"
    And the judge says "source_silent" with no quote
    When the claims are fact checked
    Then the claim is "not_shown" because of "judge_source_silent"

  Scenario: Source strength is reported and never fails a claim
    Given the source "https://news.example.com/a" says "Councilor Marlow spoke on Tuesday."
    And the source "https://www.example.com/b" says "Marlow spoke on Tuesday."
    And the source "https://other.example.org/c" says "Marlow spoke on Tuesday."
    And a claim "Marlow spoke on Tuesday." citing "https://news.example.com/a"
    And a claim "Marlow spoke on Tuesday." citing "https://news.example.com/a" and "https://www.example.com/b"
    And a claim "Marlow spoke on Tuesday." citing "https://news.example.com/a" and "https://other.example.org/c"
    And the judge supports every claim quoting "Marlow spoke on Tuesday."
    When the claims are fact checked
    Then claim 1 has a domain count of 1 and single source is "yes"
    And claim 2 has a domain count of 1 and single source is "yes"
    And claim 3 has a domain count of 2 and single source is "no"
    And all claims come out "verified"
    And the source carrying the most claims is "https://news.example.com/a"

  Scenario: A claim with two parts is supported by one verified quote for each part
    Given the source "s1" says "Councilor Marlow spoke on Tuesday. The vote was 5 to 2 after an hour."
    And a claim "Councilor Marlow spoke on Tuesday, and the vote was 5 to 2." citing "s1"
    And the judge says "supported" quoting "Councilor Marlow spoke on Tuesday." and "The vote was 5 to 2"
    When the claims are fact checked
    Then the claim comes out "verified"

  Scenario: One quote that is not in the source rejects the claim
    Given the source "s1" says "Councilor Marlow spoke on Tuesday. The vote was 5 to 2 after an hour."
    And a claim "Councilor Marlow spoke on Tuesday, and the vote was 5 to 2." citing "s1"
    And the judge says "supported" quoting "Councilor Marlow spoke on Tuesday." and "The vote was 5 to 2 and nobody objected"
    When the claims are fact checked
    Then the claim is "not_shown" because of "quote_not_in_source"

  Scenario: A quote with an ellipsis is checked piece by piece
    Given the source "s1" says "Councilor Marlow spoke on Tuesday. Then, much later, the vote was 5 to 2."
    And a claim "Councilor Marlow spoke on Tuesday, and the vote was 5 to 2." citing "s1"
    And the judge says "supported" quoting "Councilor Marlow spoke on Tuesday ... the vote was 5 to 2"
    When the claims are fact checked
    Then the claim comes out "verified"

  Scenario: A piece of an ellipsis quote that is not in the source rejects the claim
    Given the source "s1" says "Councilor Marlow spoke on Tuesday. Then, much later, the vote was 5 to 2."
    And a claim "Councilor Marlow spoke on Tuesday, and the vote was 5 to 2." citing "s1"
    And the judge says "supported" quoting "Councilor Marlow spoke on Tuesday ... the vote was unanimous"
    When the claims are fact checked
    Then the claim is "not_shown" because of "quote_not_in_source"

  Scenario: A statement about what a source does not say needs no quote when the source is silent
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "The account does not say why Councilor Marlow spoke." citing "s1"
    And the judge says "supported" with no quote because the claim is only about the source's limits
    When the claims are fact checked
    Then the claim comes out "verified"

  Scenario: A supported verdict with no quote is not shown unless the claim is only about the source's limits
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "Councilor Marlow spoke on Tuesday." citing "s1"
    And the judge says "supported" with no quote
    When the claims are fact checked
    Then the claim is "not_shown" because of "quote_not_in_source"

  Scenario: A partly supported claim needs a check and an unsupported one is not shown
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "Marlow spoke on Tuesday." citing "s1"
    And a claim "Councilor Marlow spoke." citing "s1"
    And a claim "Marlow spoke." citing "s1"
    And the judge answers the claim "Marlow spoke on Tuesday." with "partly_supported" quoting "Councilor Marlow spoke on Tuesday."
    And the judge answers the claim "Councilor Marlow spoke." with "not_supported" quoting nothing
    And the judge answers the claim "Marlow spoke." with "source_silent" quoting nothing
    When the claims are fact checked
    Then claim 1 comes out "needs_check"
    And claim 2 comes out "not_shown"
    And claim 3 comes out "not_shown"

  Scenario: A literal failure is not shown even when the judge only finds the claim partly supported
    Given the source "s1" says "Alder Vance was held for a year."
    And a claim "Ohio resident Alder Vance was held for a year." citing "s1"
    And the judge says "partly_supported" quoting "Alder Vance was held for a year."
    When the claims are fact checked
    Then the claim comes out "not_shown"

  Scenario: The judge is shown each source's title and host, labelled
    Given the source "https://news.example.com/a" has the title "Example News report" and says "Councilor Marlow spoke on Tuesday."
    And a claim "A report by Example News says Councilor Marlow spoke on Tuesday." citing "https://news.example.com/a"
    And the judge supports every claim quoting "Councilor Marlow spoke on Tuesday."
    When the claims are fact checked
    Then the judge was shown the title "Example News report" and the host "news.example.com" for "https://news.example.com/a"
    And the judge instructions allow naming a source's publisher from its title and host

  Scenario: The judge is told a statement of what a source does not say is supported when the source is silent
    Then the judge instructions say a statement that a source does not say something is supported without a quote when the source is silent

  Scenario: The writer is told to give one fact per claim and no date the sources lack
    Then the synthesis rules for a Story with a pack say one fact per claim, caveats in their own claim or in open questions, and dates only if in the sources

  Scenario: A research run keeps only verified claims, holds the rest with their reasons, and writes the summary from the verified ones
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday." and "Alder Vance was held for a year."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday." and "Ohio resident Alder Vance was held for a year."
    And the writer's summary says "Ohio resident Alder Vance was held for a year."
    When the research run is made
    Then the packet claims are exactly "Councilor Marlow spoke on Tuesday."
    And the packet holds the claim "Ohio resident Alder Vance was held for a year." as "not_shown" with the reason "unmatched_terms: Ohio"
    And the packet summary does not contain "Alder Vance"
    And the summary model was shown "Councilor Marlow spoke on Tuesday." and not "Alder Vance"
    And the packet carries its fact check counts of 1 verified and 1 not shown
    And the research packet body lists "Could not verify:" after the claims

  Scenario: A summary that fails the literal check is replaced by a plain count
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday." and "Alder Vance was held for a year."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday."
    And the writer rewrites the summary as "Councilor Marlow spoke in Ohio."
    When the research run is made
    Then the packet summary is "1 of 1 claims were verified against their sources. 0 could not be verified and are listed apart."

  Scenario: A run whose judge fails still finishes, and its claims are held as unchecked
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday." and "Alder Vance was held for a year."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday."
    And the judge fails on every call
    When the research run is made
    Then the packet has no claims
    And the packet holds the claim "Councilor Marlow spoke on Tuesday." as "unchecked" with the reason "judge_failed"
    And the packet carries its fact check counts of 0 verified and 0 not shown and 1 unchecked

  Scenario: A disagreement position that fails the literal check is labelled and kept
    Given a research run whose pages say "The vote was 5 to 2." and "The vote was 4 to 3."
    And the writer produced the disagreement "Vote" with the positions "The vote was 5 to 2." from page 1 and "The vote was 6 to 1." from page 2
    When the research run is made
    Then the position "The vote was 5 to 2." is not labelled
    And the position "The vote was 6 to 1." is labelled not shown because of "unmatched_terms: 6, 1"
    And the research packet body marks the position "The vote was 6 to 1." as not shown by the sources

  Scenario: Sources only a failed claim cited are not taken in as References
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday." and "Alder Vance was held for a year."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday." and "Ohio resident Alder Vance was held for a year."
    When the research run is made
    Then the cited-only intake would consider only page 1

  Scenario: A later reporter sees a failed claim labelled
    Given a Story whose earlier research packet has the verified claim "Councilor Marlow spoke on Tuesday.", the needs-check claim "Councilor Marlow spoke on Tuesday night.", the not-shown claim "Ohio resident Alder Vance was held for a year." and the contradicted claim "Councilor Marlow spoke on Monday."
    When the earlier research layer of the context pack is built
    Then it lists "Councilor Marlow spoke on Tuesday." under "Claims:"
    And it lists "Councilor Marlow spoke on Tuesday night." under "Needs a check (partly supported, or the attribution is unclear), do not rely on:"
    And it lists "Ohio resident Alder Vance was held for a year." under "Not shown by the sources this run had (it may still be true), do not rely on:"
    And it lists "Councilor Marlow spoke on Monday." under "Contradicted by its sources, do not rely on:"

  Scenario: A claim is verified only if the judge agrees every time it is asked
    A judge can answer differently on the same claim and the same text, so one doubt among its answers is enough.
    Given a judge that supports a claim with a real quote and then says on its second answer that attribution was lost
    When the claim is checked
    Then the claim needs a check
    And the judge was asked twice

  Scenario: A claim the judge supports every time is verified after all its passes
    Given a judge that always supports a claim with a real quote
    When the claim is checked
    Then the claim is verified
    And the judge was asked as many times as a claim needs to pass

  Scenario: A claim that failed the literal check is asked only once
    Given a judge that always supports a claim that names someone its source does not
    When the claim is checked
    Then the claim is not shown
    And the judge was asked once

  Scenario: An ordinary word that opens a sentence in the summary is not taken for a name
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday."
    And the writer rewrites the summary as "Examine the speech. Councilor Marlow spoke on Tuesday."
    When the research run is made
    Then the packet summary is "Examine the speech. Councilor Marlow spoke on Tuesday."

  Scenario: An invented person in the summary is still caught and the angle is left empty
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday."
    And the writer rewrites the summary as "Examine the speech. Jordan Quill spoke on Tuesday."
    When the research run is made
    Then the packet summary is "1 of 1 claims were verified against their sources. 0 could not be verified and are listed apart."
    And the packet angle is empty

  Scenario: A word that opens a sentence in a claim is still checked as a name
    Given the source "s1" says "Councilor resigned."
    And a claim "Marlow resigned." citing "s1"
    When the claims are fact checked without a judge
    Then the claim is "not_shown" because of unmatched terms "Marlow"

  Scenario: A possessive does not hide a name or invent a missing one
    Given the source "s1" says "The Harbor County State’s Attorney’s Office said a lead was only a lead."
    And a claim "The Harbor County State Attorney Office said a lead was only a lead." citing "s1"
    When the claims are fact checked without a judge
    Then the claim has no unmatched terms

  Scenario: A name in the editor's direction that the sources mention but the packet never wrote about is a gap
    Given a research run whose pages say "Dana Woodruff filed a court record in Pell County." and "Councilor Marlow spoke on Tuesday."
    And the writer produced the claims "Pell County has a court record." and "Councilor Marlow spoke on Tuesday."
    And the editor's direction is "Look into Dana Woodruff and Councilor Marlow."
    When the research run is made
    Then the packet names "Dana Woodruff" as a direction gap and the sources mention it
    And the packet's open questions include "The run has sources that mention Dana Woodruff but wrote nothing on Dana Woodruff."
    And the research packet body lists "Named in the direction, not covered:" after the claims

  Scenario: A name in the editor's direction that no source mentions is reported as found nothing
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday."
    And the editor's direction is "Look into Councilor Marlow and Rowan Tesk."
    When the research run is made
    Then the packet names "Rowan Tesk" as a direction gap and the sources do not mention it
    And the packet's open questions include "The run found nothing on Rowan Tesk."

  Scenario: Names the packet covers, and a direction without names, give no gap
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday."
    And the editor's direction is "Find the cases. Look into Councilor Marlow."
    When the research run is made
    Then the packet has no direction gaps


  Scenario: A name the editor told the run not to rely on is not reported as a gap
    Given a research run whose pages say "Dana Woodruff filed a court record in Pell County." and "Councilor Marlow spoke on Tuesday."
    And the writer produced the claims "Pell County has a court record." and "Councilor Marlow spoke on Tuesday."
    And the editor's direction is "Look into Councilor Marlow. Do not rely on Rowan Tesk's op-ed or on Lena Ford, and treat what Dana Woodruff filed as a lead."
    When the research run is made
    Then the packet names no direction gap for "Rowan Tesk"
    And the packet names no direction gap for "Tesk"
    And the packet names no direction gap for "Lena Ford"
    And the packet names no direction gap for "Marlow"
    And the packet's open questions do not mention "Lena Ford"

  Scenario: A name the editor excluded does not hide a name the editor wants after it
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday."
    And the editor's direction is "Do not rely on Rowan Tesk, but do look into Lena Ford."
    When the research run is made
    Then the packet names "Lena Ford" as a direction gap and the sources do not mention it
    And the packet names no direction gap for "Rowan Tesk"

  Scenario: A venue, and a name that only labels documents, are not subjects
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday."
    And the editor's direction is "Look into Councilor Marlow. Check what was presented at NeurIPS and the NeurIPS papers, the Gemini documents are leads, and The Vexley files too."
    When the research run is made
    Then the packet names no direction gap for "NeurIPS"
    And the packet names no direction gap for "The Gemini"
    And the packet names no direction gap for "Gemini"
    And the packet names no direction gap for "Vexley"

  Scenario: A leading article is not part of a name
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday."
    And the editor's direction is "Look into The Harbor Authority."
    When the research run is made
    Then the packet names "Harbor Authority" as a direction gap and the sources do not mention it

  Scenario: A claim a source contradicts, with the passage quoted, is held as contradicted
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "Councilor Marlow spoke on Monday." citing "s1"
    And the judge says "contradicted" quoting "Councilor Marlow spoke on Tuesday."
    When the claims are fact checked
    Then the claim comes out "contradicted"
    And the counts are 0 verified, 0 needs_check, 1 contradicted, 0 not_shown, 0 unchecked

  Scenario: A contradiction the judge cannot quote is only a claim the sources did not show
    Calling a claim contradicted is the stronger thing to say, so it needs the passage that says otherwise.
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "Councilor Marlow spoke on Monday." citing "s1"
    And the judge says "contradicted" with no quote
    When the claims are fact checked
    Then the claim is "not_shown" because of "quote_not_in_source"

  Scenario: A claim the sources are silent on or fall short of is not shown, and is not called false
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "Councilor Marlow spoke for an hour." citing "s1"
    And the judge says "not_supported" with no quote
    When the claims are fact checked
    Then the claim comes out "not_shown"
    And the counts are 0 verified, 0 needs_check, 0 contradicted, 1 not_shown, 0 unchecked

  Scenario: A true statement the run only had a search snippet for is not shown, in words that do not say it is false
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday." and "Councilor Marlow spoke on Tuesday."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday." and "Councilor Ada Marlow spoke on Tuesday."
    When the research run is made
    Then the research packet body lists "Not shown by the sources this run had (it may still be true):" after the claims
    And the research packet body does not contain "Rejected"

  Scenario: A packet stored before the split, with its single rejected verdict, reads as not shown
    Given a Story whose earlier research packet has the claim "Ohio resident Alder Vance was held for a year." marked "rejected" before claims were split into contradicted and not shown
    When the earlier research layer of the context pack is built
    Then it lists "Ohio resident Alder Vance was held for a year." under "Not shown by the sources this run had (it may still be true), do not rely on:"
    And the research packet body of the stored packet lists "Not shown by the sources this run had (it may still be true):"

  Scenario: A quote from a PDF's text is found although the file splits its words
    The text out of a PDF breaks words at line ends and sprays stray spaces, and the judge copies the clean words. A real passage must not be rejected for that.
    Given a source text "the channel capacity, which is the maximum value of I(H;L) over all dis- tributions on H, for a program (o r protocol)"
    Then a quote "which is the maximum value of I(H;L) over all distributions on H" is found in it
    And a quote "the (or protocol)" is not found in it

  Scenario: Removing spaces never lets a short quote match across words
    Given a source text "the car pet store"
    Then a quote "carpet" is not found in it
