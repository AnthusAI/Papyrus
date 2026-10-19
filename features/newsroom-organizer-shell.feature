Feature: Production newsroom organizer shell
  The approved newsroom appearance preserves the existing authenticated CMS.

  Scenario: The shared Board keeps Papyrus newsprint styling
    Given the native CMS Board uses the released shared Kanbus components
    When I view it at narrow and wide widths in light and dark mode
    Then headlines use the newsroom serif font and columns use newspaper rules
    And cards have square corners without retro shadows or clipped headers
    And column collapse, record selection and keyboard detail closing still work
    And the host publication palette outside the Board is unchanged

  Scenario: The complete CMS survives a navigation change
    Given an editor has an authorized session and existing newsroom records
    When an editor opens the newsroom
    Then taxonomy, concepts, knowledge search, reference curation and policies remain reachable
    And sections, procedures, messages, assignments and article editing retain their original commands
    And administrator identity merging retains its original authorization
    And Settings retains theme, motion and interface preferences
    And unsupported semantic graph merging is not reported as completed

  Scenario: Taxonomy retains its own editor
    Given an editor has an authorized session
    When an editor opens Taxonomy or a saved taxonomy category link
    Then the original taxonomy editor opens with its save and doctrine handlers
    And Topic proposals remains a separate destination
    And the retired Users and Doctrine aliases open Administration

  Scenario: Board projects native records without changing their workflow
    Given an editor is authorized to read CMS records
    When the editor opens Board
    Then native articles, current references and assignments retain their IDs and statuses
    And source links open the canonical reference lineage in the existing curator
    And unknown assignment statuses remain visible
    And mutation actions remain in their original authorized workspaces
    And a signed-out or forbidden session loads no board records

  Scenario: Complete navigation is consistent on desktop and mobile
    Given an editor opens a newsroom destination
    When the navigation is shown
    Then desktop navigation and the mobile menu show the same grouped destinations and descriptions
    And Articles and Assignments lead the Editorial work group
    And bottom tabs show icons and labels without descriptions

  Scenario: Collapsing desktop navigation returns space to the workspace
    Given the organizer sidebar is expanded
    When I activate Collapse sidebar with the keyboard
    Then the workspace grows and Expand sidebar remains reachable
    And my preference survives navigation and reload

  Scenario: The account menu uses the actual authenticated session
    Given an editor is signed in
    When I open Account menu
    Then I see the real session identity and working Settings and sign-out controls
    And the account control remains visible on narrow screens

  Scenario: A signed-out visitor cannot read private newsroom data
    Given there is no authenticated editor session
    When I open a private newsroom destination
    Then the existing access gate remains in place
    And the organizer shell grants no new role or data access

  Scenario: Unconfigured integrations remain unavailable
    Given production classifier execution is not configured
    When I inspect the newsroom controls
    Then no synthetic prediction or local service is presented as a live integration

  Scenario: Every publication uses the organizer shell
    Given any publication, with no layout option to set
    When I open the newsroom
    Then the organizer shell is shown with all of its destinations and commands

  Scenario: Settings works on a CMS hosted at the root
    Given the publication hosts its newsroom at the root path
    When I open Settings from the account menu
    Then the existing Settings page opens through the newsroom route alias
    And its cloud authorization and preference handlers are unchanged

  Scenario: CMS Settings avoids a publication's legacy reader redirect
    Given the publication redirects reader Settings under its reader base path
    When I open Settings from the newsroom account menu
    Then I open the canonical newsroom Settings route
    And the publication's legacy reader redirect remains unchanged

  Scenario: Reduced motion applies to the mobile menu itself
    Given the operating system requests reduced motion
    When I open the mobile More menu or account menu
    Then the overlay itself and its contents have no entry animation or transition

  Scenario: The staging banner does not cover application controls
    Given the staging banner is visible above the organizer
    When I navigate or move keyboard focus
    Then the organizer fits the remaining viewport
    And the header and bottom navigation remain visible without document scrolling
