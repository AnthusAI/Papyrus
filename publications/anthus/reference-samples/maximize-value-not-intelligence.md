---
id: maximize-value-not-intelligence
title: "Maximize Value, Not Intelligence"
url: https://anth.us/blog/maximize-value-not-intelligence/
source: anthus-site-content/maximize-value-not-intelligence.mdx
---

_Use the cheapest model that can do the job. Then measure whether it actually did._

In December 2023, we wrote about a text classifier that didn't work as a business. The requirement was 95% accuracy at under $200 per million classifications. GPT-4 hit the accuracy easily and cost about $1,700 per million. A great demo and a dead venture.

The fix was not a better model. It was a worse one. We went down the ladder—GPT-3.5, then Ada 2 embeddings with logistic regression, then BERT running free in a Colab notebook—and only stopped at Word2Vec, where accuracy fell far enough that the remaining savings stopped being worth it. The thesis was use the dumbest model that the problem will bear, and the only way to find that point is to go one step too far and come back.

GPT-4 is the most capable model on that chart and the only one that loses money—about $1,500 per million classifications. The winner was the least sophisticated model that still cleared the accuracy bar, and it happened to be free.

That discipline still holds in 2026. But two things changed underneath it, and together they changed what the question even is.
