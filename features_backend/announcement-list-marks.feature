Feature: Every mark the backend says is an icon the console draws
  The Announcements list and the Story drawer say each state, review and warning in words, and the backend names a Lucide icon to draw beside them. The console keeps one table from
  those names to its icons. A mark the backend can say that the table does not hold would be a line with words and no icon, or a wrong one, so the two are kept in step here.

  Scenario: The console draws every mark the backend can say
    Then the console's table of marks holds every mark the backend can say

  Scenario: The console's table holds only Lucide icons
    Then every icon in the console's table of marks is imported from Lucide
