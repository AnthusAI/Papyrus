---
title: Hello Fixture
author: Fixture Author
date: 'Sunday, September 6, 2026'
description: A fixture article for the importer.
cover: assets/hello/a.png
aliases:
  - /blog/hello-old
citations:
  a:
    type: article-journal
    title: The Cited Work
    author:
      - family: Doe
        given: Jane
    issued:
      date-parts:
        - - 2024
---
A first paragraph with a [link](https://example.com/page) and a citation [@a].

:::pull-quote{attribution="X"}
A quotable sentence.
:::

::image{src="assets/hello/a.png" alt="A" layout="full" caption="C"}

A second citation [@a] before the list.

::citations{format="apa"}
