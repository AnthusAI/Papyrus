# Agent briefs and definition of done

Put the brief below in every brief you give to an agent that changes this repository. It comes from the always-on agents track report of 2026-11-16, which found tasks closed with acceptance lines unmet, a merge before checks finished, and scenarios that tested a helper instead of the path a site runs.

## The brief

> Merge only when every check on the last commit you pushed has finished and passed; "cancelled", "pending" and "no checks" are not green, and after a merge you watch the `develop` run for your merge commit to the end. Close a task only when every acceptance line is true in the code a site runs; if a line is not met, leave the task open or file a named follow-up that blocks what depends on it, and say which. Each Gherkin scenario must go through the entry point a site uses (the runner, the handler, the command), never only a helper or a fake that repeats the logic. Before you finish: mark the task in progress when you start, write one board comment (check for an existing one first), remove your worktree and its Poetry environment, and paste the exact test commands and their last lines into the pull request.

## Definition of done for an agent pull request

1. A board task exists, is `in_progress`, and names the branch.
2. Every acceptance line and every named Gherkin scenario is listed in the pull request body as met, with the file, or as not met, with the follow-up task id.
3. All checks have finished and are green on the final commit. The test commands and their closing lines are pasted.
4. No new cap, time window, baseline entry, suppression, fallback or second reader. If a schema changes: the index added is named, both resource counts are printed, and the release order is stated.
5. After the merge: the `develop` run for the merge commit is green; one closing comment is on the task; the worktree and its environment are removed; the report says "merged to develop, not released".

See also: [AGENTS.md](../AGENTS.md) (branching, merging and releasing) and [agent-rules-detail.md](agent-rules-detail.md).
