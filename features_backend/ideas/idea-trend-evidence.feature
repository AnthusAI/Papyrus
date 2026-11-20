Feature: Cited Trends draft the same subject again only on materially new evidence
  An entity that already anchored a story draft, in any state, is not drafted again because time has passed. It is drafted again when the
  evidence now is materially more than what the earlier draft reported. Each draft reports the window it chose (its length and its
  count). The new window is compared with that report by the same kind of test the scan uses: the new count must be significantly above
  the reported rate (the upper tail of a binomial test, corrected for the number of windows tried, within 0.01). The same count over a longer
  window, or a few more than before, is not new; a surge several times larger is. A declined draft is not proposed again without new
  evidence, and with new evidence it is. The run record lists every anchor that has an earlier draft, what it reported, what the data says
  now and whether it was renewed. A draft reports its window in its evidence; a draft that does not (one filed through an operator read,
  which returns no evidence) is rebuilt from the data as of the week it was made.

  Scenario: A trend over a short window is not drafted again when the evidence has not grown
    Given a concept surged to 6 mentions in the week of "2026-10-19"
    And a story draft on the concept was filed on 2026-10-20
    When the surge continues at 7 mentions in the week of "2026-10-26"
    And the trends are selected for the week of "2026-10-26"
    Then the concept is not an anchor and the run says there is no new evidence
    And the run record shows the draft reported 6 in 1 week

  Scenario: A trend is drafted again after materially new evidence
    Given a concept surged to 6 mentions in the week of "2026-10-19"
    And a story draft on the concept was filed on 2026-10-20
    When the surge grows to 40 mentions in the week of "2026-10-26"
    And the trends are selected for the week of "2026-10-26"
    Then the concept is an anchor again
    And the run record shows the new evidence renewed the earlier draft

  Scenario: A declined trend is not proposed again without new evidence
    Given a concept surged to 6 mentions in the week of "2026-10-19"
    And a declined story draft on the concept was filed on 2026-10-20
    When the surge continues at 7 mentions in the week of "2026-10-26"
    And the trends are selected for the week of "2026-10-26"
    Then the concept is not an anchor and the run says there is no new evidence

  Scenario: A declined trend is proposed again with new evidence
    Given a concept surged to 6 mentions in the week of "2026-10-19"
    And a declined story draft on the concept was filed on 2026-10-20
    When the surge grows to 40 mentions in the week of "2026-10-26"
    And the trends are selected for the week of "2026-10-26"
    Then the concept is an anchor again
    And the run record shows the new evidence renewed the earlier draft

  Scenario: The same rate over a longer window is not new evidence
    Given a concept surged to 6 mentions in the week of "2026-10-19"
    And a story draft on the concept was filed on 2026-10-20
    When the surge continues at 6 mentions in the week of "2026-10-26"
    And the trends are selected for the week of "2026-10-26"
    Then the concept is not an anchor and the run says there is no new evidence

  Scenario: A stored draft reports the window it recorded
    Given a story draft on the concept that recorded a window of 4 weeks with 12 items
    When the earlier draft's report is read
    Then it reports 12 items in 4 weeks

  Scenario: Days passing change nothing
    Given a concept surged to 6 mentions in the week of "2026-10-19"
    And a story draft on the concept was filed on 2026-10-20
    When the surge continues at 7 mentions in the week of "2026-10-26"
    And the trends are selected for the week of "2026-10-26"
    Then the concept is not an anchor and the run says there is no new evidence
    And the retired seven-day cooldown is not in the run record

  Scenario: An entity with no earlier draft is unaffected
    Given a concept surged to 6 mentions in the week of "2026-10-19"
    And a story draft on another concept was filed on 2026-10-20
    When the trends are selected for the week of "2026-10-19"
    Then the concept is an anchor
