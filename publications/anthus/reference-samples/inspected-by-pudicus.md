---
id: inspected-by-pudicus
title: "Inspected by Pudicus"
url: https://anth.us/blog/inspected-by-pudicus/
source: anthus-site-content/inspected-by-pudicus.mdx
---

Agent swarms write a lot of code. They also skip git hooks. `--no-verify` is right there in the man page, and they've learned it. The hook we actually need is the one that scans for secrets and other sensitive information *before* the commit. After a key is in git history, you're rotating credentials and rewriting history. That's the expensive part.

The volume is the same either way: because AI coding costs have collapsed, these things can fill a repo overnight. A human on every diff is already theater. The leftover control isn't a person staring at the patch. It's whether the secret scanner ran on this tree, before the commit.

CI will not save you here. By the time a pipeline sees the commit, the secret is already in history.

Think of a crate of apples leaving a farm. The farm owner doesn't personally bite into every apple before it goes on the truck. The crate gets an "Inspected By #247" sticker. A specific, trusted process checked it on the loading dock. No sticker, the truck doesn't leave.

Here the crate is a git commit. The inspection is a secret scan: Gitleaks, Tactus, whatever you pin. The sticker means that scanner ran on *this* tree, before the commit. The expensive failure is not "CI went red." It's a key sitting in `git log`.
