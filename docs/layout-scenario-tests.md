# Layout scenario tests

Executable BDD scenarios for the newspaper layout solver.

Executable BDD scenarios live in `features/*.feature`. They describe newspaper
layout behaviors in durable product language: open a named scenario at a
viewport size, flip to a page, and assert outcomes such as no cropped measured
lines, no furniture overlap, no dead continuation columns, and a specific image
template winning.

Scenario URLs such as `/?scenario=shared-blank-column-pressure` select named
fixture content through the same content repository boundary used by the app.
They are not a renderer-side bypass.

Do not put BDD scenario fixtures in production content records. Test scenarios
belong in `lib/layout-scenarios.ts` so they remain deliberate, reproducible
examples.

The step definitions use Playwright to inspect both rendered DOM rectangles and
the solved layout exposed as `window.__PAPYRUS_LAYOUT__`. That lets a scenario
check the visible page and the solver decision without encoding rectangle math
inside the feature file.
