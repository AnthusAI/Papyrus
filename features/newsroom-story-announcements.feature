@brand-agnostic
Feature: A Story shows where it was announced
  An editor opening a Story in the drawer sees where it was announced: one line for each Delivery, under the Announcement that decided it. The lines are read through the Story's
  "announces" relation from the Story's side, in one indexed read; nothing lists a table and nothing is subscribed to. Each state is a mark and words together, never colour alone,
  in flat fills with no borders. A Delivery that is due and has had no attempt says "Overdue"; one whose attempt has no answer yet says "Outcome unknown" until it is settled; a
  blocked draft shows its review flag once for its Announcement. These scenarios run on the local preview's seeded Stories, which name no real account or address, and nothing
  here sends: X stays off.

  Scenario: A Story that was announced shows one line for each Delivery
    Given I open the Story "harbor safety review" in the drawer at 1440 by 1000
    Then the drawer should show the Announcement "Story published" with 2 lines, one for each Delivery
    And in that drawer Announcement the "Email" line should read "Sent" with an icon
    And in that drawer Announcement the "X" line should read "Dry run: not sent" with an icon

  Scenario: A Story in a roundup shows the roundup beside its own Announcement
    Given I open the Story "harbor safety review" in the drawer at 1440 by 1000
    Then the drawer should show the Announcement "Roundup" with 1 line, one for each Delivery
    And in that drawer Announcement the "Email" line should show the review "Waits for a person to release it" with an icon

  Scenario: A Story that was never announced says so
    Given I open the Story with no announcements in the drawer
    Then the drawer should say "This Story has not been announced."

  Scenario: A due Delivery with no attempt shows "Overdue" and a blocked draft shows its flag once
    Given I open the Story "lighthouse keepers" in the drawer at 1440 by 1000
    Then the drawer should show the Announcement "Story published" with 2 lines, one for each Delivery
    And in that drawer Announcement the "X" line should say "Overdue" with an icon
    And in that drawer Announcement the "Email" line should read "Blocked: check failed" with an icon
    And the drawer should show the review flag once

  Scenario: A Delivery with an attempt left started shows "Outcome unknown"
    Given I open the Story "harbor safety review" in the drawer at 1440 by 1000
    Then the drawer should show the Announcement "Correction" with 1 line, one for each Delivery
    And in that drawer Announcement the "X" line should say "Outcome unknown" with an icon

  Scenario: The drawer's lines use icons with words, flat fills and no borders, and fit a phone
    Given I open the Story "lighthouse keepers" in the drawer at 375 by 812
    Then every state in the drawer should be an icon together with words
    And nothing in the drawer's announcements should have a border
    And the Story page should not scroll sideways
