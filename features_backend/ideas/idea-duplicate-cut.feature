Feature: Each site learns its own cut for near-duplicate ideas
  A generated idea is dropped as a near-duplicate when its text is at least as similar to a story or another idea as the site's cut. The
  cut is learned from what the site's editors did with earlier ideas: ideas spiked as duplicates against ideas moved forward. It is the
  smallest similarity at which the 95% lower bound of the duplicate share reaches the site's target precision. While a site has too few
  decisions the fixed 0.5 applies and the run record says so.

  Scenario: Editors' duplicate spikes set the cut
    Given a site whose editors spiked forty ideas as duplicates of stories and moved twenty unrelated ideas forward
    When the site's duplicate cut is learned
    Then the cut is learned from sixty decisions and lies above the unrelated ideas and at or below the duplicates
    And the run record reports the cut with the lower bound that justified it

  Scenario: Too few decisions keep the fixed fallback and say so
    Given a site whose editors spiked one idea as a duplicate and moved one idea forward
    When the site's duplicate cut is learned
    Then the cut is 0.5 and not learned
    And the run record says "no learned cut: too few decisions"

  Scenario: A spike for another reason is not a duplicate label
    Given a site whose editors spiked ideas for being off topic and moved ideas forward
    When the site's duplicate cut is learned
    Then the off topic spikes are not counted as decisions

  Scenario: An operator's threshold wins over the learned cut
    Given a site whose editors spiked forty ideas as duplicates of stories and moved twenty unrelated ideas forward
    When the cut is resolved with an operator threshold of 0.7
    Then the cut is 0.7 and not learned

  Scenario: Story context is not cut off by a fixed number of days
    Given a site with a story published two hundred days ago and one published ten days ago
    When the story context is loaded without a window
    Then both stories are in the context and the window is the span of the site's own stories
