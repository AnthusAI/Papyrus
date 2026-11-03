Feature: Everything a model writes from sources is fact checked, in layers, before anyone relies on it
  A model that is told to use only its sources still invents. A research packet once named a man "Rodney Reid" where the source said
  only "Reid", and called a man a Tennessee resident where the source said he lived somewhere else. A rule in the prompt does not stop
  that, so the shared fact check (contract fact-check/v1) reads every claim against the text of the sources it cites. The first layer
  is plain code. Every name, number, date, place and quotation in a claim must appear in the cited sources, and code does not forgive
  a missing one. The second layer is an independent judge: a separate model call that is told nothing about how the claim was written
  and must answer with a quote taken word for word from the source, which code then looks for. A claim is verified only when the
  literal check passes, the judge says the source supports it with a quote that really is there, and the claim does not present as
  fact something the source only attributes to a party. A failed judge never counts as a pass: the claim is unchecked. The judge
  cannot rescue a claim that failed the literal check. The check also reports how many independent domains stand behind each claim,
  and that never fails a claim. In a multi-search research packet, a claim that is not verified is never deleted and never passed on
  as fact: it is held in a list of unverified claims with the reasons, the summary is written again from the verified claims alone,
  sources only a failed claim cited are not taken in as References, and a later reporter sees the failed claims labelled.

  Scenario: A name the sources only half give fails the literal check
    Given the source "s1" says "Councilor Marlow said the plan would cost the town more each year."
    And a claim "Councilor Ada Marlow said the plan would cost the town more each year." citing "s1"
    When the claims are fact checked without a judge
    Then the claim is "unverified" because of unmatched terms "Ada"

  Scenario: A place the sources never mention fails the literal check
    Given the source "s1" says "Alder Vance, who lives in Brightwater, was held for a year."
    And a claim "Ohio resident Alder Vance was held for a year." citing "s1"
    When the claims are fact checked without a judge
    Then the claim is "unverified" because of unmatched terms "Ohio"

  Scenario: Numbers match however they are written
    Given the source "s1" says "The town agreed to pay 200,000 dollars. Its 2024 budget was $2.5 million, up 12 percent. Fifteen homes flooded."
    And a claim "The town paid $200,000 from a 2024 budget of $2.5 million, up 12%, and 15 homes flooded." citing "s1"
    When the claims are fact checked without a judge
    Then the claim has no unmatched terms

  Scenario: A number the sources do not give fails the literal check
    Given the source "s1" says "The town agreed to pay $200,000."
    And a claim "The town agreed to pay $250,000." citing "s1"
    When the claims are fact checked without a judge
    Then the claim is "unverified" because of unmatched terms "250,000"

  Scenario: A quotation must appear in the sources, however the quotation marks are typed
    Given the source "s1" says "She called it “a plain mistake” on Tuesday."
    And a claim 'She called it "a plain mistake".' citing "s1"
    And a claim 'She called it "a grave error".' citing "s1"
    When the claims are fact checked without a judge
    Then claim 1 has no unmatched terms
    And claim 2 is "unverified" because of unmatched terms "a grave error"

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
    Then the claim is "unverified" because of "quote_not_in_source"
    And the judge verdict recorded for the claim is "not_supported"

  Scenario: A judge that fails leaves the claim unchecked and the others still checked
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "Councilor Marlow spoke on Tuesday." citing "s1"
    And a claim "Councilor Marlow spoke." citing "s1"
    And the judge fails on the claim "Councilor Marlow spoke on Tuesday." and supports the others quoting "Councilor Marlow spoke"
    When the claims are fact checked
    Then claim 1 comes out "unchecked"
    And claim 2 comes out "verified"
    And the counts are 1 verified, 0 unverified, 1 unchecked

  Scenario: A literal failure cannot be overridden by a supportive judge
    Given the source "s1" says "Alder Vance was held for a year."
    And a claim "Ohio resident Alder Vance was held for a year." citing "s1"
    And the judge says "supported" quoting "Alder Vance was held for a year."
    When the claims are fact checked
    Then the claim is "unverified" because of unmatched terms "Ohio"

  Scenario: An allegation stated as fact is flagged even when the judge finds it supported
    Given the source "s1" says "The complaint alleges that the officer ignored the witness."
    And a claim "The officer ignored the witness." citing "s1"
    And the judge says "supported" quoting "the officer ignored the witness" and reports the attribution lost
    When the claims are fact checked
    Then the claim is "unverified" because of "attribution_lost"

  Scenario: A judge that says the source is silent leaves the claim unverified
    Given the source "s1" says "Councilor Marlow spoke on Tuesday."
    And a claim "Councilor Marlow spoke on Tuesday." citing "s1"
    And the judge says "source_silent" with no quote
    When the claims are fact checked
    Then the claim is "unverified" because of "judge_source_silent"

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

  Scenario: A research run keeps only verified claims, holds the rest with their reasons, and writes the summary from the verified ones
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday." and "Alder Vance was held for a year."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday." and "Ohio resident Alder Vance was held for a year."
    And the writer's summary says "Ohio resident Alder Vance was held for a year."
    When the research run is made
    Then the packet claims are exactly "Councilor Marlow spoke on Tuesday."
    And the packet holds the unverified claim "Ohio resident Alder Vance was held for a year." with the reason "unmatched_terms: Ohio"
    And the packet summary does not contain "Alder Vance"
    And the summary model was shown "Councilor Marlow spoke on Tuesday." and not "Alder Vance"
    And the packet carries its fact check counts of 1 verified and 1 unverified
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
    And the packet holds the unverified claim "Councilor Marlow spoke on Tuesday." with the reason "judge_failed"
    And the packet carries its fact check counts of 0 verified and 0 unverified and 1 unchecked

  Scenario: A disagreement position that fails the literal check is labelled and kept
    Given a research run whose pages say "The vote was 5 to 2." and "The vote was 4 to 3."
    And the writer produced the disagreement "Vote" with the positions "The vote was 5 to 2." from page 1 and "The vote was 6 to 1." from page 2
    When the research run is made
    Then the position "The vote was 5 to 2." is not labelled
    And the position "The vote was 6 to 1." is labelled unverified because of "unmatched_terms: 6, 1"
    And the research packet body marks the position "The vote was 6 to 1." as could not verify

  Scenario: Sources only a failed claim cited are not taken in as References
    Given a research run whose pages say "Councilor Marlow spoke on Tuesday." and "Alder Vance was held for a year."
    And the writer produced the claims "Councilor Marlow spoke on Tuesday." and "Ohio resident Alder Vance was held for a year."
    When the research run is made
    Then the cited-only intake would consider only page 1

  Scenario: A later reporter sees a failed claim labelled
    Given a Story whose earlier research packet has the verified claim "Councilor Marlow spoke on Tuesday." and the unverified claim "Ohio resident Alder Vance was held for a year."
    When the earlier research layer of the context pack is built
    Then it lists "Councilor Marlow spoke on Tuesday." under "Claims:"
    And it lists "Ohio resident Alder Vance was held for a year." under "Unverified, do not rely on:"
