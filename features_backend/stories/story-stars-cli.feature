Feature: Editors find Stories by star rating and change it from the command line
  The editors rate Stories privately, and the layouts order Stories by a rolling recency bucket, then the effective quality rating, then newest first.
  `papyrus stories list` shows those signals as columns after the existing ones (stars, source, votes, bucket, type, words, published), filters by
  --stars, --min-stars, --max-stars and --type, and sorts by --sort stars or --sort rank, which is the order the Articles and Posts page shows first.
  The rating is read from the rows the list already reads, so a list costs no request per Story. `stories show` prints the same signals and who
  rated and when. `stories set-stars` sets the editor's value through the newsroom's setItemStars mutation, from 1 to 5, and 0 clears it. A Story
  nobody rated shows 0 stars, source none and 0 votes everywhere. Ratings are private and reach no published row.

  Background:
    Given the signed-in site has rated Stories "a" with 2 stars, "b" with 5 stars, "c" unrated and "d" with 4 stars

  Scenario: The listing shows stars, source and votes
    When an editor lists the Stories
    Then the Story "b" is listed with 5 stars from the source "editor" and 1 vote
    And the Story "c" is listed with 0 stars from the source "none" and 0 votes

  Scenario: Filtering by exactly 3 stars or fewer
    When an editor lists the Stories with "--stars 5"
    Then only the Stories "b" are listed

  Scenario: Filtering by at least 4 stars
    When an editor lists the Stories with "--min-stars 4"
    Then only the Stories "b, d" are listed

  Scenario: Sorting by stars puts rated Stories high to low and unrated last
    When an editor lists the Stories with "--sort stars"
    Then the Stories are listed in the order "b, d, a, c"

  Scenario: Sorting by rank gives the order the page shows
    When an editor lists the Stories with "--sort rank"
    Then the Stories are listed in the order "c, a, b, d"

  Scenario: Showing a Story prints its rating details
    When an editor shows the Story "b"
    Then the shown signals say 5 stars from the source "editor" and the rating names "An Editor"

  Scenario: Showing an unrated Story prints 0 stars and no rating line
    When an editor shows the Story "c"
    Then the shown signals say 0 stars from the source "none" and there is no rating line

  Scenario: Setting a rating prints the previous and the new rating
    When an editor sets the stars of the Story "a" to "4"
    Then the output says previous 2 and stars 4 and the newsroom was asked to set the stars to 4

  Scenario: Setting 0 clears the rating
    When an editor sets the stars of the Story "a" to "0"
    Then the newsroom was asked to clear the stars

  Scenario Outline: A rating outside 0 to 5 is refused
    When an editor sets the stars of the Story "a" to "<stars>"
    Then the command fails saying the stars run from 0 to 5 and the newsroom was not asked

    Examples:
      | stars |
      | 6     |
      | -1    |

  Scenario: A dry run sends nothing
    When an editor sets the stars of the Story "a" to "3" as a dry run
    Then the newsroom was not asked
