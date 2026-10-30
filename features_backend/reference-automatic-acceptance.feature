@backend @reference-automatic-acceptance
Feature: A confident prediction nobody voted on is accepted automatically, once the editors' usual time has passed
  A monitor delivers each Reference as pending, with the Cyclotron's verdict: a label and how sure it is. Editors Accept or Reject, but
  not everything gets a vote. Every few minutes the monitoring router looks at each publication's pending References and accepts one
  by itself when three things are true. The Cyclotron's verdict is the publication's positive label. The Cyclotron is at least as sure
  as a threshold learned from this publication's own editors: the smallest confidence at which the editors' votes on positive verdicts
  show, with 95 percent statistical confidence (the Wilson lower bound), an accept rate at or above the target precision, 90 percent by
  default. And nobody voted for as long as the editors normally take, learned from this publication's own vote latency: the time from
  delivery to the vote, at the 90th percentile by default. There are no fixed numbers in it. With too few votes, or votes that
  disagree, no threshold qualifies and nothing is accepted; the reason goes into one JSON log line per publication per run. The
  feature is on for every publication unless its router configuration says "autoAccept": {"enabled": false}. An automatic acceptance
  is written like an editor's accept, except that its actor is "auto:cyclotron", so the router never sends it to the Cyclotron as an
  editor's label, and its reason says what it rested on. An editor can still Reject or re-Accept it; that is an ordinary vote. A
  Reference an editor has touched is never changed. The Cyclotron is a fake in these scenarios and nothing touches production.

  Background:
    Given a router with the publication "anth-us" and no autoAccept setting

  Scenario: A publication with no autoAccept setting accepts a confident unvoted item once its votes qualify
    Given the editors accepted 40 References the Cyclotron was 90% sure were relevant, each within 2 days
    And a pending Reference delivered 5 days ago that the Cyclotron judged relevant with 95% confidence
    When the router runs its automatic acceptance
    Then the Reference is accepted by "auto:cyclotron"
    And its reason names the 95% confidence, the 90% threshold, the 40 votes and the 2 day delay
    And the log line for "anth-us" says status "ran", threshold 0.9, candidates 1 and accepted 1

  Scenario: Nothing is accepted before the editors' usual time has passed
    Given the editors accepted 40 References the Cyclotron was 90% sure were relevant, each within 2 days
    And a pending Reference delivered 1 day ago that the Cyclotron judged relevant with 95% confidence
    When the router runs its automatic acceptance
    Then the Reference stays pending
    And the log line for "anth-us" says status "ran", threshold 0.9, candidates 0 and accepted 0

  Scenario: A prediction below the learned threshold stays pending
    Given the editors accepted 40 References the Cyclotron was 90% sure were relevant, each within 2 days
    And a pending Reference delivered 5 days ago that the Cyclotron judged relevant with 70% confidence
    When the router runs its automatic acceptance
    Then the Reference stays pending
    And the log line for "anth-us" says status "ran", threshold 0.9, candidates 0 and accepted 0

  Scenario: A prediction that the item is not relevant is never accepted
    Given the editors accepted 40 References the Cyclotron was 90% sure were relevant, each within 2 days
    And a pending Reference delivered 5 days ago that the Cyclotron judged not relevant with 99% confidence
    When the router runs its automatic acceptance
    Then the Reference stays pending

  Scenario: Too few votes means nothing is accepted, and the log says why
    Given the editors accepted 5 References the Cyclotron was 90% sure were relevant, each within 2 days
    And a pending Reference delivered 5 days ago that the Cyclotron judged relevant with 95% confidence
    When the router runs its automatic acceptance
    Then the Reference stays pending
    And the log line for "anth-us" says status "skipped" because "no confidence reaches the target precision"

  Scenario: Votes that disagree mean nothing is accepted
    Given the editors accepted 20 References the Cyclotron was 90% sure were relevant, each within 2 days
    And the editors rejected 20 References the Cyclotron was 90% sure were relevant, each within 2 days
    And a pending Reference delivered 5 days ago that the Cyclotron judged relevant with 95% confidence
    When the router runs its automatic acceptance
    Then the Reference stays pending
    And the log line for "anth-us" says status "skipped" because "no confidence reaches the target precision"

  Scenario: Without any editor vote there is no delay to learn, so nothing is accepted
    Given a pending Reference delivered 5 days ago that the Cyclotron judged relevant with 95% confidence
    When the router runs its automatic acceptance
    Then the Reference stays pending
    And the log line for "anth-us" says status "skipped" because "no editor vote latency yet"

  Scenario: A Reference an editor reopened is left alone
    Given the editors accepted 40 References the Cyclotron was 90% sure were relevant, each within 2 days
    And a pending Reference delivered 5 days ago that the Cyclotron judged relevant with 95% confidence
    And an editor reopened that Reference
    When the router runs its automatic acceptance
    Then the Reference stays pending

  Scenario: An automatic acceptance does not teach the threshold
    Given the editors accepted 40 References the Cyclotron was 90% sure were relevant, each within 2 days
    And the Cyclotron accepted 30 more References automatically that it was 95% sure about
    When the router runs its automatic acceptance
    Then the log line for "anth-us" says status "ran", threshold 0.9, candidates 0 and accepted 0
    And the log line counts 40 votes

  Scenario: Switching it off with "enabled": false
    Given the publication's autoAccept setting is {"enabled": false}
    And the editors accepted 40 References the Cyclotron was 90% sure were relevant, each within 2 days
    And a pending Reference delivered 5 days ago that the Cyclotron judged relevant with 95% confidence
    When the router runs its automatic acceptance
    Then the Reference stays pending
    And there is no log line for "anth-us"

  Scenario: The target precision and the delay quantile are settings, and bad values are refused
    Then the autoAccept setting {"precision": 0.95, "latencyQuantile": 0.5} is accepted as written
    And the autoAccept setting {"precision": 1.2} is refused
    And the autoAccept setting {"latencyQuantile": 0} is refused
    And the autoAccept setting {"enabled": "yes"} is refused
    And the autoAccept setting {"maximum": 10} is refused

  Scenario: The router sends nothing about an item it accepted, to the Cyclotron or anyone else
    Given the editors accepted 40 References the Cyclotron was 90% sure were relevant, each within 2 days
    And a pending Reference delivered 5 days ago that the Cyclotron judged relevant with 95% confidence
    When the router runs its automatic acceptance
    Then the Reference is accepted by "auto:cyclotron"
    And the Reference records an automatic accept by the Cyclotron that is not a human label and no Message is written

  Scenario: A monitor that delivers by a fixed rule has its delivery accepted on delivery
    Given the monitor delivers by a fixed rule that takes every collected item
    And a pending Reference the router is about to deliver for "anth-us"
    When the router delivers the item
    Then the Reference is accepted by "auto:rule"
    And its reason names the monitor "hn" and the rule "every collected item"
    And the Reference records an automatic accept by the rule that is not a human label and no Message is written

  Scenario: Switching it off keeps a rule monitor's delivery pending for an editor
    Given the monitor delivers by a fixed rule that takes every collected item
    And the publication's autoAccept setting is {"enabled": false}
    And a pending Reference the router is about to deliver for "anth-us"
    When the router delivers the item
    Then the Reference stays pending

  Scenario: The backfill lists the pending deliveries of a rule monitor without changing them
    Given the site "distinctive" whose monitor "ttab" delivered 35 pending References by its rule
    When the operator runs references auto-accept for "distinctive" as a dry run
    Then the backfill lists 35 deliveries from "ttab" and nothing was written

  Scenario: The backfill accepts them by rule, and an editor's own vote is left alone
    Given the site "distinctive" whose monitor "ttab" delivered 35 pending References by its rule
    And an editor already rejected one of them
    When the operator runs references auto-accept for "distinctive"
    Then 34 deliveries are accepted by "auto:rule" and the editor's Reject stands

  Scenario: The backfill leaves Cyclotron-decided deliveries to the confidence rules
    Given the site "distinctive" whose monitor "ttab" delivered 35 pending References by its rule
    And the monitor "hn" delivered 3 pending References the Cyclotron judged relevant
    When the operator runs references auto-accept for "distinctive" as a dry run
    Then the backfill lists 35 deliveries from "ttab" and nothing was written
