@brand-agnostic @board-refresh-fixtures
Feature: The newsroom board refreshes cheaply
  A visible board asks for what changed every five minutes, on one timer. It does not re-read every story and every assignment every thirty
  seconds, and it does not read the published stories twice. Reloading the page always shows the latest, the board also refreshes when the tab
  becomes visible again or the window regains focus (at most once a minute, so quick tab switching costs nothing), and after the editor's own
  actions on the board. There are no realtime subscriptions. These scenarios use a fake clock and synthetic stories and never touch production.

  Scenario: One timer refreshes the board every five minutes
    Given a visible board with its first load done
    When four minutes and fifty-nine seconds pass
    Then the board has not refreshed
    When one more second passes
    Then the board refreshes once, on a single timer

  Scenario: A hidden tab makes no requests
    Given a visible board with its first load done
    When the tab is hidden for thirty minutes
    Then no timer is running and the board has not refreshed
    When the tab becomes visible again
    Then the board refreshes once and the five-minute timer starts again from that moment

  Scenario: Quick tab switching does not hammer the backend
    Given a board that refreshed less than a minute ago
    When the editor switches away and back ten times and focuses the window each time
    Then the board does not refresh

  Scenario: The editor's own action shows at once
    Given a visible board with its first load done
    When the editor closes a story they edited in the side panel
    Then the board refreshes immediately without waiting for the timer
    And a refresh already running is followed by exactly one more, never run twice at the same moment

  Scenario: A refresh asks only for changed stories
    Given stages that already show their newest stories
    When the board refreshes and one story changed and another moved to a later stage
    Then each stage is asked only for stories updated since its newest one
    And the changed story replaces its old copy, the moved story leaves its old column, and the loaded pages stay
    And a refresh where nothing changed leaves the board exactly as it was

  Scenario: Published stories are read once
    Given the board's data loading
    Then published stories come from the Published stage like every other stage and there is no separate published read
