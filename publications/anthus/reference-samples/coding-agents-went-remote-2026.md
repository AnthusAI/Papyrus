---
id: coding-agents-went-remote-2026
title: "The Year the Coding Agents Went Remote"
url: https://anth.us/blog/coding-agents-went-remote-2026/
source: anthus-site-content/coding-agents-went-remote-2026.mdx
---

There was a look you could spot at any tech conference in 2025: an engineer walking through the halls carrying a laptop cracked open at hip level, carefully, like a tray of water glasses. Closing the lid killed the agent loop and killed whatever the agent was working on, so the lid stayed open.

That was a year ago. It feels archaic now.

Through 2024 and into early 2025, coding agents lived inside your IDE or your terminal. They ran on your clock, on your machine, in your process. If the laptop slept, the agent stopped. If you wanted to check on it, you walked back to the desk.

If you used more than one agent product — and by mid-2025 most serious practitioners were running Cursor and Claude Code at minimum, often Codex as well — you were the integration layer. You switched tabs, copied context from one conversation into another, and babysat every session individually. The agents could not see each other's work.

I built Kanbus to solve the part of this problem that was solvable without waiting for vendors. The idea was simple: if every issue is a JSON file inside a Git repository, then any agent that can clone the repo can read the board and write to it. Git is the transport. The repository is the shared memory.

What changed was not one thing. Three trends hit at the same time, and they multiplied. Cheaper tokens made long loops viable. Agents got better at running long. The harnesses shipped real remote orchestration.
