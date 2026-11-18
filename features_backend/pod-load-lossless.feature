@pod
Feature: papyrus pod load puts a pod's notes into the newsroom, losing nothing and writing only what changed
  `papyrus pod load POD` signs in to the site and loads the pod's notes as the newsroom's content items. It runs `pod check` first, and a pod with problems is
  not loaded and does not even sign in. A note of a class that is an Item (Article, Post, Page) becomes a Story: the note's `type` is the Item's `type`, its
  `stage` is the Item's `stage`, its `section` link names the Item's `section`, and the front matter and the body are kept word for word. The other lifecycle
  keys (`format`, `rating`, `reviewedBy`, `reviewedOn`, `reviewedHash`, `spikedReason`, `heldReason`) land on the Item under the same names, beside the
  note's id and the commit the pod was at. Nothing is dropped or renamed.

  The load records the commit it came from, so the pod must be a Git repository with that commit and nothing uncommitted. Git history is linked by the
  commit and never replayed: a load writes one version of a note that changed and no version of a note that did not. A Story that a person has since
  changed in the newsroom (a version they saved, a stage they moved) is theirs: the load leaves it alone and says it is now owned by the newsroom. There
  is no force flag. A note is found again through its permanent id, so loading the same pod twice writes nothing the second time.

  Background:
    Given a signed-in newsroom with no stories
    And a started pod
    And the pod file "water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0031
      type: papyrus:Section
      title: Water
      ---
      Stories about water.
      """
    And the pod file "slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0032
      type: papyrus:Article
      title: Slow water
      description: How a village learned to hold water in the ground.
      date: 2026-11-10
      section: "[[water]]"
      stage: copywriting
      format: explainer
      rating: 3
      reviewedBy: Ada Example
      reviewedOn: 2026-11-12
      ---
      Slow water keeps rain on the land a little longer.
      """
    And the pod note "slow-water.md" is stamped with the hash of its body
    And the pod is a git repository with everything committed

  Scenario: Every lifecycle key lands on the same-named field, and nothing is renamed
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 0
    And the load signed in once
    And the story for the note "slow-water.md" has the type "article"
    And the story for the note "slow-water.md" has the stage "copywriting"
    And the story for the note "slow-water.md" has the section "water"
    And the story for the note "slow-water.md" carries the pod key "format" with the value "explainer"
    And the story for the note "slow-water.md" carries the pod key "rating" with the value "3"
    And the story for the note "slow-water.md" carries the pod key "reviewedBy" with the value "Ada Example"
    And the story for the note "slow-water.md" carries the pod key "reviewedOn" with the value "2026-11-12"
    And the story for the note "slow-water.md" carries the pod key "reviewedHash" as the note says it
    And the story for the note "slow-water.md" keeps the note's front matter and body word for word

  Scenario: Keys the note does not carry are not invented
    When I load the pod with "papyrus pod load POD"
    Then the story for the note "slow-water.md" carries no pod key "spikedReason"
    And the story for the note "slow-water.md" carries no pod key "heldReason"

  Scenario Outline: A spiked or held note keeps its reason
    Given the pod file "later.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0033
      type: papyrus:Post
      title: Later
      stage: <stage>
      <reasonKey>: <reason>
      ---
      Not now.
      """
    And the pod's changes are committed
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 0
    And the story for the note "later.md" has the stage "<stage>"
    And the story for the note "later.md" carries the pod key "<reasonKey>" with the value "<reason>"

    Examples:
      | stage  | reasonKey    | reason             |
      | spiked | spikedReason | Nothing new to say |
      | held   | heldReason   | Wait for the vote  |

  Scenario: The load records the note's id and the commit it came from
    When I load the pod with "papyrus pod load POD"
    Then the story for the note "slow-water.md" records the note's id
    And the story for the note "slow-water.md" records the commit the pod is at
    And the pod report says "commit: "

  Scenario: Loading twice writes nothing
    Given the pod is loaded
    When I load the pod again with "papyrus pod load POD"
    Then the pod command exits with status 0
    And nothing was written to the newsroom
    And the story for the note "slow-water.md" has 1 version
    And the pod report says "1 unchanged"

  Scenario: A note that changed is one new version, not a replay of its history
    Given the pod is loaded
    And the pod file "slow-water.md" has "hold water in the ground" replaced by "keep water in the ground"
    And the pod's changes are committed
    And the pod file "slow-water.md" has "keep water in the ground" replaced by "keep rain in the ground"
    And the pod's changes are committed
    When I load the pod again with "papyrus pod load POD"
    Then the pod command exits with status 0
    And the story for the note "slow-water.md" has 2 versions
    And the story for the note "slow-water.md" keeps the note's front matter and body word for word
    And the story for the note "slow-water.md" records the commit the pod is at
    And the pod report says "1 updated"

  Scenario: A Story a person saved a version of is left alone
    Given the pod is loaded
    And a person saved a new version of the story for the note "slow-water.md"
    And the pod file "slow-water.md" has "hold water in the ground" replaced by "keep water in the ground"
    And the pod's changes are committed
    When I load the pod again with "papyrus pod load POD"
    Then the pod command exits with status 0
    And nothing was written to the newsroom
    And the pod report says "slow-water.md: now owned by the newsroom"
    And the story for the note "slow-water.md" has the body "A person rewrote this."

  Scenario: A Story a person moved to another stage is left alone
    Given the pod is loaded
    And a person moved the story for the note "slow-water.md" to the stage "held"
    And the pod file "slow-water.md" has "hold water in the ground" replaced by "keep water in the ground"
    And the pod's changes are committed
    When I load the pod again with "papyrus pod load POD"
    Then nothing was written to the newsroom
    And the pod report says "slow-water.md: now owned by the newsroom"
    And the story for the note "slow-water.md" has the stage "held"

  Scenario: A dry run says what would be written and writes nothing
    When I load the pod with "papyrus pod load POD --dry-run"
    Then the pod command exits with status 0
    And the pod report says "slow-water.md: would be created"
    And the pod report says "dry run, nothing written"
    And nothing was written to the newsroom

  Scenario: A pod with a problem is not loaded and does not sign in
    Given the pod file "slow-water.md" has "stage: copywriting" replaced by "stage: pubished"
    And the pod's changes are committed
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 1
    And the pod report says "Nothing was loaded."
    And the pod report says "key 'stage' is 'pubished'"
    And the load did not sign in
    And the newsroom has no stories

  Scenario: Changes that are not committed are refused, because the commit would not describe what is loaded
    Given the pod file "slow-water.md" has "hold water in the ground" replaced by "keep water in the ground"
    When I load the pod with "papyrus pod load POD"
    Then the pod command fails with the message "has changes that are not committed"
    And the load did not sign in
    And the newsroom has no stories

  Scenario: A pod that is not in Git is refused
    Given a started pod with an Article "story.md" carrying these keys:
      """
      stage: idea
      """
    When I load the pod with "papyrus pod load POD"
    Then the pod command fails with the message "is not a git repository with a commit"
    And the newsroom has no stories

  Scenario: Notes of a class that is not an Item are counted and named, not loaded
    When I load the pod with "papyrus pod load POD"
    Then the pod report says "not loaded by this version: 1 Section note(s)"
