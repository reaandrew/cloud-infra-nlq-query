# Phase 5 — GDS restyle, DEMO branding, stage progress bar, complexity-tiered quick start

_Status: delivered and verified live (2026-04-13)._

## What phase 5 delivers

1. **Strip every "cinq" reference** from the user-visible surface.
   Branding becomes explicit: a **DEMO** tag in the header and a
   GDS-style phase banner that says exactly that. This is a public
   demonstration, not a product.

2. **Restyle the SPA to GOV.UK Design System (GDS) conventions** —
   black header, no card shadows, sharp corners, GDS green primary
   buttons, gov.uk blue links, yellow focus highlights, Helvetica/Arial
   typography. Crown logo and "GOV.UK" wordmark deliberately **not**
   used (this isn't a real government service).

3. **Stage progress panel** for the Query view: while a request is in
   flight, the SPA shows a 4-row progress display (Embed → Retrieve →
   Generate SQL → Athena) that animates against the median observed
   stage durations. When the response arrives, the synthetic timeline
   is replaced with the **real** per-stage timings from the API.

4. **Complexity-tiered quick start library** in the Query view:
   examples are now grouped into **four levels** showing the range of
   queries the system supports, from a trivial histogram up to a
   four-way orphan-detection join. Each tab carries a level number,
   each level has a one-line description, and each level has 3
   curated example questions.

5. **Bedrock global inference profile** for the NLQ Lambda. Phase 4 was
   pinned to `anthropic.claude-sonnet-4-6` (single-region eu-west-2),
   which started returning `ServiceUnavailableException` under load
   and burning the API Gateway 30-second budget on retries. Phase 5
   switches to `global.anthropic.claude-sonnet-4-6` — the cross-region
   inference profile that load-balances across every region Anthropic
   publishes the model to. This was the actual fix for the 503s.

## Branding changes

| Surface | Before | After |
|---|---|---|
| `<title>` | `cinq · NLQ for AWS Config` | `AWS Config NLQ — DEMO` |
| Page meta description | `cinq — natural-language…` | `DEMO — natural-language…` |
| Header brand mark | `cinq` + tagline in a slate sidebar | Black bar with white **DEMO** chip + "AWS Config NLQ" |
| Phase banner | _(none)_ | Blue **DEMO** tag + "This is a demonstration service. Do not enter real production data." |
| Footer | "cloud-infra-nlq-query" link | **DEMO** prefix + same source link |
| Favicon | Slate square with chart icon | Black square with bold white "D" |

The literal string "cinq" appears nowhere in the SPA HTML, JS, or CSS
output any more. (It's still in the underlying terraform resource names
because renaming live AWS resources is destructive — that's an internal
naming concern, not a user-facing one.)

## GDS design system

### Tokens

A single `@theme` block in `web/src/index.css` declares the palette,
typography and radius tokens. The colours are taken directly from the
GOV.UK Design System palette page:

| Token | Value | Purpose |
|---|---|---|
| `--color-text` | `#0b0c0c` | Body text, near-black |
| `--color-text-secondary` | `#505a5f` | Muted labels |
| `--color-link` | `#1d70b8` | gov.uk blue, all links |
| `--color-link-hover` | `#003078` | Darker on hover |
| `--color-green` | `#00703c` | Primary "Ask the question" button |
| `--color-yellow` | `#ffdd00` | Focus highlight |
| `--color-red` | `#d4351c` | Error states |
| `--color-blue` | `#1d70b8` | Tags, accents, the header underline |
| `--color-bg-grey` | `#f3f2f1` | Muted surfaces and code blocks |
| `--color-border` | `#b1b4b6` | Hairline rules between rows |
| `--color-border-strong` | `#0b0c0c` | Thick black rules under table headers |
| `--font-sans` | `"Helvetica Neue", Helvetica, Arial, sans-serif` | GDS Transport substitute |
| `--font-mono` | `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` | Code, ARNs, IDs |
| `--radius-*` | `0` | Sharp corners everywhere |

### The yellow focus

GDS focus is the most distinctive thing about the design system. Every
interactive element gets the same treatment when keyboard-focused:
yellow background with a black 4px box-shadow underneath, a single
unmistakable visual cue. Implemented via `:focus-visible` selectors in
`index.css` so it only fires for keyboard nav, not click.

### Shape and surfaces

- **No shadows.** The shadow-as-elevation card pattern is replaced with
  flat surfaces and either no border, a 1px grey border, or a thick 2px
  black border under section headings.
- **Sharp corners.** Buttons, cards, inputs, badges — all `radius: 0`.
  GDS doesn't round corners.
- **No card chrome around content sections.** This was the explicit
  course-correct from phase 4: the user pointed out that GDS doesn't
  wrap content in bordered card boxes the way a SaaS dashboard does.
  The Dashboard view now uses flat section headings and govuk-summary-list
  patterns; only structurally-meaningful containers (the question
  textarea, the SQL code block, the progress panel, the results table)
  retain explicit borders.

### Layout

- **Black header bar** spanning the viewport width, with a 10px
  `--color-blue` underline. Contains the DEMO chip, the brand text, and
  the API key affordance.
- **Phase banner** below the header — borrows the GOV.UK Frontend
  pattern (`govuk-phase-banner`) — with the DEMO tag and the demo
  warning sentence.
- **Top tabs** for Dashboard / Query (replaces the slate sidebar from
  phase 4). Active tab gets a 5px blue bottom border.
- **Max-width 1100px** container on every page section, centred.
- **Footer** with a 2px blue top border and a single sentence reiterating
  the DEMO disclaimer.

### Typography

- `gds-h1` = 48px / 700 / line-height 1.04
- `gds-h2` = 36px / 700 / line-height 1.11
- `gds-h3` = 24px / 700 / line-height 1.25
- Body = 19px / 1.31
- Mobile breakpoint at 40em scales everything down (32 / 24 / 18 / 16)

Headings are tight, body is generous. Same proportions GDS publishes.

## Stage progress panel

`web/src/components/QueryProgress.tsx`.

### What the user sees

While a query is running, a panel appears below the question form with:

- A heading: **"Running query"** → **"Query complete"** → **"Query failed"**
- A live "Total" timer counting up in real time
- 4 stage rows: Embed question / Retrieve schemas / Generate SQL /
  Run Athena query — each with its own progress bar

Each stage row shows:

- A circular numbered marker that turns into a green check on completion
- The stage label and a one-line description
- A trailing time slot ("queued" → "in progress…" → real ms duration)
- A horizontal progress bar coloured by state (grey-blue while in
  progress → blue light when synthetically complete → green when the
  real timing comes back → red on error)

### How it works

Bedrock and API Gateway HTTP API don't expose mid-stream progress
events, so the SPA fakes a believable timeline based on observed
median latencies:

| Stage | `estimatedMs` |
|---|---:|
| Embed question | 250 |
| Retrieve schemas | 250 |
| Generate SQL | 5500 |
| Run Athena query | 2500 |
| **Synthetic total** | **8500** |

A `setInterval` ticks the elapsed time at 50 ms intervals. Each row
computes its own `[stageStart, stageEnd]` range against the running
`now` value and renders accordingly:

- Before `stageStart` → "queued", grey
- Inside the range → "in progress…", blue, fill = `(now - start) / span`
- Past `stageEnd` → "synthetic complete", blue-light, fill 100%

When the actual API response arrives, `done=true` plus the real
`timings` object are passed in. Each stage's display switches from the
synthetic value to the real `embed_ms` / `retrieve_ms` / `generate_ms` /
`athena_ms` from the response, the marker turns green, and the panel
heading flips to "Query complete".

### The "what if reality outruns the estimate" edge case

The first version had a bug: if the real request took longer than the
synthetic 8.5s, every stage would render as "complete" even though the
panel still said "Running query". That's a confusing lie.

Fix: the **last stage** stays in the active state with `progress = 0.95`
indefinitely, no matter how long `now` runs past the synthetic
endpoint. Earlier stages still complete normally. So the user sees
stages 1-3 turn green and stage 4 stay actively in-progress for as
long as the request takes — which is the truth. When the response
arrives, all four switch to their real durations.

### Failure path

If the API returns an error, `error=true` is passed in and whichever
stage was active when the error fired turns red with a triangle-error
icon. The header flips to "Query failed".

## Quick start library — complexity-tiered

`web/src/data/examples.ts` + the example tab section in `QueryView.tsx`.

### Four levels, three examples each

**Level 1 — Basics.** Single-table aggregations. One `GROUP BY`, no
JSON probing. The fastest queries in the catalogue.
1. Resource type histogram
2. EC2 instances per account
3. Top accounts by resource count

**Level 2 — JSON fields.** Reaches into the opaque `configuration` /
`tags` JSON columns via `json_extract_scalar`.
1. Largest EBS volumes (size, type, encrypted)
2. EC2 instances by Environment tag
3. Lambda runtimes histogram

**Level 3 — Cross-resource joins.** Two resource types joined via an
ID extracted from JSON, producing a WITH-CTE pattern.
1. Instance ↔ Volume (attachments[0].instanceId)
2. Lambda ↔ IAM role (configuration.role → role.arn)
3. EBS volume ↔ KMS key (configuration.kmsKeyId)

**Level 4 — Advanced.** Three or more resource types, orphan
detection, inventory pivots.
1. Subnet occupancy (3-way LEFT JOIN + COALESCE)
2. VPC inventory (4-way `COUNT(*) FILTER (WHERE …)` pivot)
3. Orphan KMS keys (anti-join via `LEFT JOIN … WHERE NULL`)

### How the user sees it

- Tabs are labelled `1 Basics`, `2 JSON fields`, `3 Cross-resource joins`,
  `4 Advanced`. Active tab gets a filled blue level chip; inactive tabs
  get a grey one. The numbering itself is the visual gradient.
- Below the tab bar, a single-line callout with a blue left border
  ("Level 2 · JSON fields — Reaches into the opaque configuration…")
  tells the user what kind of query they're about to see.
- Below that, three example items per level. Each is a flat link-style
  block (no card chrome) with a bold blue underlined title, a one-line
  description of what it shows off, and the literal question in italics
  so the user can see what gets sent before they click.
- Clicking an example pastes the question into the textarea and
  immediately fires the request — no second click required.

### Why the complexity framing matters

The phase 4 grouping was topic-based (Inventory / Compute / Security /
Networking). That tells you _what_ kind of resource each example
touches but says nothing about _what makes the example interesting_.
Reframing as complexity levels shows the **range** of the underlying
system: the same natural-language layer handles both "count rows by
type" and "find KMS keys not referenced by any consumer". A demo
visitor walking the four tabs from L1 → L4 sees the system getting
progressively more impressive without needing to read the docs.

## The Bedrock 503 fix

Phase 4 used `anthropic.claude-sonnet-4-6` directly. During phase 5
verification this started returning `ServiceUnavailableException`
intermittently. boto3's adaptive-retry config was happily burning 50+
seconds on exponential backoff before giving up — well past API
Gateway HTTP API's hard 30-second integration timeout — causing every
slow query to surface as a 503 to the user.

### Three changes in `lambda/nlq/handler.py`

1. **Cap retries** so we fail fast instead of eating the request
   budget:
   ```python
   _BEDROCK_CFG = Config(
       retries={"max_attempts": 2, "mode": "standard"},
       read_timeout=22,
       connect_timeout=4,
   )
   ```
2. **Lower `max_tokens`** from 1500 to 1000 — observed worst-case SQL
   output is around 900 tokens, so 1000 is enough margin and shaves
   generation time on simpler queries.
3. **Tighten the Athena polling timeout** to 22s so it can't push past
   the integration cap on its own.

### One change in `terraform/app/variables.tf`

```hcl
variable "chat_model_id" {
  default = "global.anthropic.claude-sonnet-4-6"
}
```

The `global.` prefix is a Bedrock cross-region inference profile that
load-balances requests across every region Anthropic publishes the
model to. Capacity is materially higher than any single region's
ON_DEMAND endpoint.

### One change in `terraform/app/api.tf` (IAM)

The IAM grant for `bedrock:InvokeModel` had to be widened to cover
both inference-profile ARNs and the underlying foundation-model ARNs
(an inference profile invocation is granted on the profile + each
backing model ARN it routes to):

```hcl
Resource = [
  "arn:aws:bedrock:*::foundation-model/*",
  "arn:aws:bedrock:*:*:inference-profile/*",
]
```

Wildcard scope is acceptable in this sandbox; in a tighter environment
you'd enumerate the exact models the inference profile routes to.

### Result

Same query that was returning 503 after 31s is now returning 200 in
~12s. The progress panel reflects the real timings; users see the
Generate stage taking ~5-7s consistently rather than hitting the
boto3 retry storm.

## Files changed

### SPA — `web/src/`
- `index.css` — full GDS token rewrite
- `App.tsx` — no functional change, default view stays Dashboard
- `index.html` — title, meta, fonts (dropped Inter + JetBrains Mono in
  favour of system Helvetica/Arial)
- `public/favicon.svg` — black square with white "D"
- `components/AppShell.tsx` — sidebar → black header + phase banner +
  top tabs + footer
- `components/ApiKeyDialog.tsx` — GDS look, simpler copy
- `components/QueryProgress.tsx` (new) — 4-stage progress panel
- `components/ui/Button.tsx` — GDS green primary, sharp corners
- `components/ui/Card.tsx` — flat surface, optional thick header rule
- `components/ui/Badge.tsx` — GDS tag (uppercase, sharp, coloured fill)
- `components/ui/Dialog.tsx` — thick black border, square corners
- `components/ui/Skeleton.tsx` — flat grey shimmer
- `views/DashboardView.tsx` — flat layout, no card chrome, summary list
- `views/QueryView.tsx` — uses QueryProgress, complexity-tiered tabs,
  flat example items
- `data/examples.ts` — new 4-level taxonomy with 12 examples

### Backend
- `lambda/nlq/handler.py` — retries + timeouts + max_tokens
- `terraform/app/variables.tf` — `chat_model_id` switched to global profile
- `terraform/app/api.tf` — IAM widened to cover inference profiles

## Verification

End-to-end via Playwright in a real browser, viewport 1440×1000:

| Check | Result |
|---|---|
| `<title>` is `AWS Config NLQ — DEMO`, no "cinq" | ✅ |
| Header has DEMO chip, phase banner, no card-style sidebar | ✅ |
| Dashboard renders flat (no bordered cards), correct KPIs | ✅ |
| Tab switch to Query | ✅ |
| Quick start tabs show 1 / 2 / 3 / 4 numbered chips | ✅ |
| Tab click switches active level + description + examples | ✅ |
| Click an example → progress panel appears | ✅ |
| Progress panel header changes from "Running query" to "Query complete" | ✅ |
| Real per-stage timings replace synthetic ones on completion | ✅ |
| Generated SQL block renders with blue left border, grey background | ✅ |
| Retrieved schemas list shows 5 entries with distance scores | ✅ |
| Results table renders with thick black header rule | ✅ |
| 503 errors no longer occur on Sonnet 4.6 calls | ✅ (~12s vs 31s before) |

## What's next

Phase 6 candidates if the demo earns continued investment:
- Pre-compute the dashboard stats on a schedule and serve them from
  S3, dropping the warm Lambda from the path (currently paying for
  Athena polls per refresh).
- Bedrock streaming via `invoke_model_with_response_stream` — would
  let the SPA stream the SQL into the code block as Claude writes it,
  rather than waiting for the full response.
- A "share this query" deep-link so example URLs can be sent around
  Slack/Teams.
- A real "save my own queries" affordance backed by DynamoDB.
- Code-splitting to drop the SPA bundle below 200 KB initial.
