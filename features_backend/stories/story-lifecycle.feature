Feature: A Story is one content item with one lifecycle
  Everything a publication makes is a Story: one content item that is created when work on it starts and keeps
  the same identity through research, reporting, writing, illustration, typesetting and publication. There is no
  separate record for the idea, the draft and the published piece. The Story moves through a fixed list of
  stages, and the board in the newsroom shows one card for each Story in the column of its stage.

  Three rules keep that simple. A person's review is never a stage: an agent that needs a person asks with a
  review request and the Story stays where it is. Each new version of the copy replaces the one before it on the
  board, so a Story is never listed twice. And the Assignments that research, report and write are work on a
  Story, so each one names the Story it belongs to.

  Scenario: A Story moves through nine stages, in this order
    When an editor asks which stages a Story can be in
    Then the stages of a Story are, in order:
      | stage        |
      | idea         |
      | assignment   |
      | reporting    |
      | copywriting  |
      | illustration |
      | typesetting  |
      | published    |
      | held         |
      | spiked       |

  Scenario: A person's review is not a stage
    When an editor asks which stages a Story can be in
    Then no stage of a Story is called "review"
    And placing a new Story at the stage "review" is refused, and the refusal lists the stages a Story can be in

  Scenario: A new Story begins as the first draft version of its own lineage
    When the Story "Hospitals are paying ransoms" is created at the stage "idea" in the section "news"
    Then the new Story is version 1 of its lineage and nothing came before it
    And the new Story is a draft that no reader can see
    And the new Story is on the board in the column "idea"

  Scenario: A Story with no section stores none
    When the Story "An untitled thought" is created at the stage "idea" with no section
    Then the new Story has no section
    And the new Story is on the board in the column "idea"

  Scenario: A Story that has no type yet is stored as untyped
    Given the site names no default Story type
    When the Story "Hospitals are paying ransoms" is created at the stage "idea" in the section "news"
    Then the new Story has the type "untyped"

  Scenario: The first Assignment on a new subject creates its Story
    When the Assignment "assignment-reporting-1" is opened for the new subject "Hospitals are paying ransoms"
    Then a Story titled "Hospitals are paying ransoms" is created at the stage "assignment"
    And the Assignment works on that Story

  Scenario: A later Assignment on the same Story creates nothing
    Given the Story with the lineage "content-item-hospitals-abc123" already exists
    When the Assignment "assignment-copywriting-1" is opened for the Story with the lineage "content-item-hospitals-abc123"
    Then no new Story is created
    And the Assignment works on the Story with the lineage "content-item-hospitals-abc123"

  Scenario: The same subject opened by the same Assignment always gets the same Story
    When the Assignment "assignment-reporting-1" is opened for the new subject "Hospitals are paying ransoms"
    And the Assignment "assignment-reporting-1" is opened for the new subject "Hospitals are paying ransoms" again
    Then both openings name the same Story

  Scenario: An Assignment that names no Story is refused
    When the newsroom asks which Story the Assignment "assignment-orphan-1" works on and it names none
    Then the question is refused, naming the Assignment "assignment-orphan-1"
    And the refusal says that every research, reporting and copywriting Assignment is work on one content item

  Scenario Outline: Moving a Story to another stage moves its one card
    Given a Story on the board in the column "<from>"
    When the Story moves to the stage "<to>"
    Then the Story is on the board in the column "<to>" and in no other column

    Examples:
      | from        | to           |
      | idea        | assignment   |
      | assignment  | reporting    |
      | reporting   | copywriting  |
      | copywriting | illustration |
      | typesetting | published    |
      | copywriting | held         |
      | idea        | spiked       |

  Scenario: A version that a newer one replaced leaves the board
    Given a Story on the board in the column "copywriting"
    When a newer version of the Story replaces it
    Then the replaced version is in no column of the board

  Scenario: A Story whose only version is a draft is still on the board
    Given a Story whose only version is a draft at the stage "reporting"
    Then that draft is on the board in the column "reporting"

  Scenario Outline: Every type a site invents is a Story type, and the engine's own records are not Stories
    Then a record of the type "<type>" <is or is not> a Story

    Examples:
      | type      | is or is not |
      | article   | is           |
      | post      | is           |
      | roundup   | is           |
      | untyped   | is           |
      | wiki_page | is not       |
      | doctrine  | is not       |
      | page      | is not       |
      | sub-task  | is not       |

  Scenario: The steps of a Story's checklist are not listed as Stories
    Given these records in the newsroom:
      | title                        | type     |
      | Hospitals are paying ransoms | article  |
      | Copy edit                    | sub-task |
      | Fact check                   | sub-task |
      | A short note                 | post     |
    When the newsroom lists the records without checklist steps
    Then the list is "Hospitals are paying ransoms" and "A short note"
