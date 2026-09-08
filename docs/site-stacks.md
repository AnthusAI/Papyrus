# Pluggable site stacks

Ops UI and publication/reader output are **independent plugins**. They are not
a forced pair.

A site may use Pretext/newsprint (or Markus, or a future renderer) for reader
pages while using Shadcn `/newsroom` for steering — or any other mix. Pilobolus
choosing Markus does **not** imply a Pilobolus-only ops UI. Adopting Shadcn
ops does **not** force Markus on the reader.

Kanbus: PPY-43704a / PPY-5a5570. Related: [site-theme-packs.md](site-theme-packs.md),
[site-hosting.md](site-hosting.md).

## Config seam (`SiteStack`)

`getSiteStack(brand)` in `lib/site-stack.ts` splits `SiteBrand` into:

```ts
type SiteStack = {
  ops: {
    chrome: "app" | "newsprint";   // newsroom shell
    themePack: ThemePackId;        // Shadcn token pack
    themeTokens: ThemePackTokens;
  };
  publication: {
    renderer: { kind: "pretext" | "markus" };
  };
  hosting: { kind: "amplify-ssr" | "amplify-static" };
};
```

`SiteBrand` also carries an optional `rootRoute` (see `lib/site-brand.ts`):
`{ kind: "reader" }` (default — render the publication home page at `/`) or
`{ kind: "redirect", destination }` (send `/` to a path/URL, e.g. for a
CMS-only deployment whose reader lives on another app).
```

`app/layout.tsx` exposes the live choice on `<html>`:

- `data-theme-pack` / `data-ops-chrome` — ops stack
- `data-renderer` — publication stack (`pretext` \| `markus`)

Do not infer `renderer` from `themePack` or `opsChrome`. Do not infer ops
theme from `renderer`.

## What v1 wires vs leaves as an extension point

| Layer | v1 | Later |
| --- | --- | --- |
| **Ops chrome** | Shared Shadcn `NewsroomAppShell` when `opsChrome` is `app` | Optional newsprint ops shell |
| **Ops theme** | Packs `papyrus`, `threat-intelligence`, `pilobol-us` | Additional packs |
| **Renderer** | Field is configured and published as `data-renderer` | Markus/static reader path; extra kinds |
| **Hosting** | Typed on the brand | Amplify WEB static pipeline |

The Next.js reader still uses the existing Pretext path. Selecting
`renderer.kind: "markus"` does **not** change `/newsroom` and does not yet
swap the reader. That is the explicit extension point — not a lock to Pretext,
and not a signal to implement Markus inside ops.

## Legal mixes (all valid)

| Ops chrome | Theme pack | Renderer | Shipping brand |
| --- | --- | --- | --- |
| `app` | `papyrus` | `pretext` | Papyr.us (default) |
| `app` | `threat-intelligence` | `pretext` | Threat Intelligence |
| `app` | `pilobol-us` | `markus` | Pilobol.us reader (static) + Pilobolus CMS (SSR `/newsroom`) |
| `app` | `pilobol-us` | `pretext` | Legal mix; not a shipping brand |
| `app` | `papyrus` | `markus` | Legal mix; not a shipping brand |

Common hosting pairings (`amplify-ssr`+`pretext`, `amplify-static`+`markus`)
are documented in [site-hosting.md](site-hosting.md). They are examples, not
locks.
