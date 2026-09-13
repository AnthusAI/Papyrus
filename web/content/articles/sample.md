---
title: Agents work better with less freedom
deck: One Markus source, two renderers — Markus static and Pretext newsprint.
authors:
  - Ada Lovelace
date: 2026-09-06
section: Pilobol.us
---

Developers are learning that reliable agents need less freedom, not more.

Across demos and tool launches, builders kept circling the same answer.

:::pull-quote{attribution="Editorial principle"}
The practical breakthrough is not giving agents a bigger sandbox.
:::

## Planning state

Read-only tools. An inline `code_span` should not be confused with a block.

```python
def plan():
    return "read only"
```

:::card-grid{columns="2"}
:::card{title="Read"}
Look before you leap.
:::
:::card{title="Write"}
Only after planning.
:::
:::

:::two-up{ratio="1:1"}
:::column
Planning state keeps risk low.
:::
:::column
Implementation state is where damage happens.
:::
:::

:::figure{src="../assets/state-diagram.svg" alt="State diagram" caption="Two states, one agent"}
:::

The lesson is not that agents are over.
