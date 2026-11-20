Feature: A site sets its own idea rules, including an idea that starts from a real item and states an invented premise
  What an idea must show before it is filed is a setting of the site, not a fixed rule of the engine. A site's monitor settings may carry
  idea rules: how many accepted References a context-pack idea must cite (two by default) and whether one sentence must cite that many together, which
  verdicts of the point check let an idea through (only "adds" by default), whether a repeated point or talk about how the story came to be fails the
  check, and the mode. In the default mode an idea must say more than a summary of its Reference. In the premise-led mode the writer starts from one real
  Reference and states an invented premise on its own: the sentences about the real item rest on that item and are cited, the premise is
  labelled as invented wherever the idea is shown, and nothing judges it against the source. A site that sets nothing behaves exactly as before.

  Scenario: A site that sets no idea rules gets the standard ones
    Given a site whose monitor settings carry no idea rules
    Then the idea rules are two References, a joint sentence, only the verdict "adds" and the evidence mode

  Scenario: A wrong idea rule is refused with the name of the setting
    Given a site whose monitor settings set the minimum number of References to 0
    Then the settings are refused and the message names "monitorStories.ideaRules"

  Scenario: A context-pack idea that never cites two References together is dropped by default
    When a context pack idea whose sentences each cite one Reference is written under the standard rules
    Then the pack files no idea

  Scenario: A site that asks for no joint sentence files that idea
    When a context pack idea whose sentences each cite one Reference is written under rules that need no joint sentence
    Then the pack files 1 idea

  Scenario: A site that wants three References refuses an idea citing two and says so to the writer
    When a context pack idea citing two References is written under rules that need three
    Then the pack files no idea
    And the idea was dropped for citing fewer than 3 accepted References

  Scenario: A site that lets "restates" through files an idea the standard rules would drop
    When a context pack idea that only restates its sources is written under the standard rules
    Then the pack files no idea
    When the same idea is written under rules whose passing verdicts are "adds" and "restates"
    Then the pack files 1 idea

  Scenario: A premise-led idea starts from one real Reference and states the premise apart
    When a premise-led run drafts an idea from a Reference that has no editor reason or comment
    Then the drafting run files 1 idea
    And the idea records the premise as invented, apart from the sentences that rest on the source
    And no point check was asked

  Scenario: A premise-led run whose writer offers no premise files nothing
    When a premise-led run is answered with an empty premise
    Then the drafting run files no idea and skips the Reference as "no_premise_offered"

  Scenario: The default mode is unchanged by the premise-led mode
    When a run in the default mode drafts an idea
    Then the idea is judged for a point and records no premise
