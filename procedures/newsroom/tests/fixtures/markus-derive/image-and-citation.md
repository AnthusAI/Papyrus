---
title: Image and citation
citations:
  a:
    type: webpage
    title: Source A
    URL: https://example.com/a
    issued:
      date-parts: [[2024, 1, 2]]
  b:
    type: webpage
    title: Source B
    URL: https://example.com/b
    issued:
      date-parts: [[2023, 5, 6]]
---

Intro with a cite [@a] and again [@a].

::image{src="images/a.png" alt="A" layout="full"}

Later a pair [@b; @a].

::citations{format="apa"}
