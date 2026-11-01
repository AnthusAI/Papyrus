Feature: The site Cyclotron learns which links and packs editors want
  Two classifiers are derived for the site Cyclotron without configuration: reference-link-fit and idea-pack-fit.
  Their examples come only from decisions people made, with the reasons they gave. A trained version replaces the
  statistical rule only after it beats the rule on decisions it was not trained on.

  Scenario: Link examples come from decisions people made
    Given a person rejected a suggested link with the reason code "off-topic" and the note "Different product line"
    And automation accepted a suggested link
    When the reference-link-fit examples are built
    Then the learning example count is 1
    And the example is labeled "does-not-fit" with the explanation "off-topic: Different product line"
    And the example carries the features similarity, shared concepts, shared host, publication-date gap and both human-accepted

  Scenario: Pack examples come from what people did with the idea
    Given a person moved the idea from pack "pack-a" forward
    And a person spiked the idea from pack "pack-b" with the note "Too thin"
    And automation spiked the idea from pack "pack-c"
    When the idea-pack-fit examples are built
    Then the learning example count is 2
    And the pack "pack-a" example has the label "worth-an-idea"
    And the pack "pack-b" example is labeled "not-worth-an-idea" with the explanation "Too thin"

  Scenario: A trained link classifier that does not beat the Wilson cut is not promoted
    Given 80 earlier and 20 later link decisions where the Wilson cut is right about every one
    And a trained version that gets half the later decisions wrong
    When the trained link classifier is evaluated against the rule
    Then the link classifier is not promoted

  Scenario: A trained link classifier that beats the Wilson cut is promoted and switches the consumer
    Given 80 earlier and 20 later link decisions where the Wilson cut misses every acceptance
    And a trained version that gets every later decision right
    When the trained link classifier is evaluated against the rule
    Then the link classifier is promoted
    And suggestions are marked by the trained version
    But before the evaluation suggestions were marked by the rule

  Scenario: A trained pack classifier that does not beat surprise ordering is not promoted
    Given held-out ideas where surprise already orders forwarded ideas first
    And a trained version that orders them the other way
    When the trained pack classifier is evaluated against surprise ordering
    Then the pack classifier is not promoted
    And the packs stay in surprise order

  Scenario: A trained pack classifier that beats surprise ordering is promoted and orders the queue
    Given held-out ideas where surprise orders spiked ideas first
    And a trained version that orders forwarded ideas first
    When the trained pack classifier is evaluated against surprise ordering
    Then the pack classifier is promoted
    And the packs are in the trained version's order
