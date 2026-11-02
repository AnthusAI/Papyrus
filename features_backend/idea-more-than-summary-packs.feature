Feature: A pack idea joins its References, never writes from titles, and says something its References do not
  A context pack is a theme the newsroom's own activity surfaced: several accepted References that belong together. An idea written from a pack is
  worth filing only when it connects them, and it can connect only what it has read. So a pack idea needs at least one sentence that cites two References
  together (otherwise it is two summaries side by side), and it may cite only References that have a summary beyond their title. A pack whose
  References are known only by their titles is skipped before the model is asked and is offered again on the next run, when a summary may exist. A Reference's
  summary is the first that exists of: the summary Message linked to it, the metadata attachment's summary, the curation attachment's summary, and the
  preview attachment's description when it is more than the title.
  A pack idea gets the same second check as a single-item idea. A model that is told nothing about how the idea was written reads it against each Reference it
  cites, one at a time, and says whether it makes a claim of its own that none of them makes on its own. Listing what each source says side by side is not such
  a claim. The check fails closed: an idea that restates its sources, makes a claim they do not support, repeats itself or talks about its own process is dropped
  with its reason, and so is an idea whose check gave no usable answer. A dry run asks the check too. One idea failing it does not stop the pack's other ideas.
  A pack all of whose ideas were rejected is not written again on every run: the run remembers the rejection and the pack's connections (its accepted
  References, the comments in it, the links between them and what editors wrote on those links), and offers the pack again only when one of them is new.

  Scenario: A pack whose References have only titles is skipped and the model is not asked
    Given a pack of four accepted References of which one has a summary
    When the pack is written
    Then the pack's model is asked 0 times
    And the pack is skipped as "nothing_to_add"

  Scenario: A pack idea with no sentence citing two References together is dropped before it is checked
    Given a pack of four accepted References that all have summaries
    And the model writes an idea whose sentences each cite a single Reference
    When the pack is written
    Then the pack files no idea
    And the idea was dropped because it has "no_joint_sentence"
    And the pack's point check is asked 0 times

  Scenario: A pack idea with a sentence citing two References together that says something of its own is filed
    Given a pack of four accepted References that all have summaries
    And the model writes an idea with a sentence citing two References together
    And the pack's point check answers that the idea says something no single source says
    When the pack is written
    Then the pack files 1 idea
    And the pack's point check is asked 1 times
    And the point check was shown each Reference the idea cites on its own

  Scenario: A pack idea may not cite a Reference that has only a title
    Given a pack of four accepted References of which two have summaries
    And the model writes an idea with a sentence citing a Reference without a summary
    When the pack is written
    Then the pack files no idea
    And the idea was dropped because it has "cites_reference_without_summary"

  Scenario Outline: A pack idea that says nothing its References do not is dropped with the reason
    Given a pack of four accepted References that all have summaries
    And the model writes an idea with a sentence citing two References together
    And the pack's point check answers that the idea <answer>
    When the pack is written
    Then the pack files no idea
    And the idea was dropped because the point check found "<reason>"

    Examples:
      | answer                                       | reason                 |
      | lists what each source says                  | no_point_beyond_source |
      | claims something its sources do not support  | point_unsupported      |
      | repeats itself                               | repeats_itself         |
      | talks about how the idea came to be          | exposes_process        |

  Scenario: A pack idea whose point check gave no usable answer is dropped
    Given a pack of four accepted References that all have summaries
    And the model writes an idea with a sentence citing two References together
    And the pack's point check gives no usable answer
    When the pack is written
    Then the pack files no idea
    And the idea was dropped because the point check gave no usable answer

  Scenario: A Reference's summary comes from the first source that has one
    Given a Reference whose preview attachment describes it and whose curation attachment summarises it
    Then its summary is the curation attachment's
    Given a Reference whose preview attachment only repeats its title
    Then it has no summary

  Scenario: A pack whose ideas were all rejected is not written again until it has a new connection
    Given a context pack run on a site whose pack ideas the point check rejects
    When the run is repeated with nothing new in the pack
    Then the pack's model was not asked again and the run says the pack is "already_rejected"
    When another accepted Reference joins the pack
    And the run is repeated
    Then the pack's model was asked again and the run says the pack was tried again because of a new connection
