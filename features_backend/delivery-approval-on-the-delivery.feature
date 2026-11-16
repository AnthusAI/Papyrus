Feature: A Delivery carries its own approval
  Approval lives on the Delivery, because two channels of one Announcement can differ: LinkedIn may need a person while X goes by the publication's policy. Each
  Delivery records the approval it runs under ("none", "soft" or "hard"), where that value came from (approvalPolicy), and the one version that was approved:
  who approved it and when. A later version than the approved one is not approved. The Announcement holds none of this: it keeps only the decision and its
  release time.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3

  Scenario: A Delivery records approval, its source, the version, who and when
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel  | account  | approval | policy                      |
      | linkedin | page-one | hard     | channel override: linkedin  |
    When the person "ellie" approves version 1 of the Delivery "linkedin" "page-one"
    Then the Delivery row "linkedin" "page-one" holds
      | field           | value                      |
      | approval        | hard                       |
      | approvalPolicy  | channel override: linkedin |
      | approvedVersion | 1                          |
      | approvedBy      | ellie                      |
      | approvedAt      | 2026-11-16T14:00:00Z       |

  Scenario: Two Deliveries of one Announcement hold different approval values
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel  | account  | approval | policy                      |
      | linkedin | page-one | hard     | channel override: linkedin  |
      | x        | handle-1 | none     | publication default         |
    Then the catalog holds 1 Announcement
    And the Delivery row "linkedin" "page-one" holds
      | field    | value |
      | approval | hard  |
    And the Delivery row "x" "handle-1" holds
      | field          | value               |
      | approval       | none                |
      | approvalPolicy | publication default |
      | approvedBy     | system              |

  Scenario: A later version than the approved one is not approved
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel  | account  | approval |
      | linkedin | page-one | hard     |
    And the person "ellie" approves version 1 of the Delivery "linkedin" "page-one"
    When the Story "slow-water" changes to version 4
    Then the Delivery row "linkedin" "page-one" holds
      | field           | value |
      | version         | 2     |
      | approvedVersion | 1     |
    And the Delivery "linkedin" "page-one" is not approved

  Scenario: A Delivery with no approval policy is refused
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel  | account  | approval | policy |
      | linkedin | page-one | hard     |        |
    Then the call is refused saying "approvalPolicy"
    And the catalog holds 0 Deliveries
    And the catalog holds 0 Announcements

  Scenario: An approval value outside none, soft and hard is refused
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel  | account  | approval |
      | linkedin | page-one | maybe    |
    Then the call is refused saying "approval is one of"
    And the catalog holds 0 Announcements

  Scenario: Two people approving at once do not overwrite each other
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel  | account  | approval |
      | linkedin | page-one | hard     |
    When two people read the Delivery "linkedin" "page-one" and both approve version 1
    Then exactly one approval is saved and the other is told the Delivery changed
