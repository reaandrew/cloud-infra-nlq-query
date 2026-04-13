# Phase 4 — React SPA + stats endpoints + S3/CloudFront hosting

_Status: delivered and verified live (2026-04-13)._

## What phase 4 delivers

A front-end for the cinq NLQ system, served from a custom subdomain:

- **Live URL**: <https://nlq.demos.apps.equal.expert>
- **API URL** (unchanged from phase 3): <https://api.nlq.demos.apps.equal.expert>

Two views in the SPA:

1. **Dashboard** — KPI cards (total resources, distinct accounts/types/regions),
   horizontal bar chart of the top resource types, snapshot freshness panel,
   and a top-accounts table. Reads from four new unauthenticated `GET /stats/*`
   endpoints.
2. **Query** — natural-language input with a curated grid of premade example
   queries grouped into Inventory / Compute / Security / Networking tabs.
   Click an example → fires the API → renders the generated SQL, retrieved
   schemas, per-stage timings, and the result table.

The front-end is a React SPA written in TypeScript with Tailwind v4 and
hand-built shadcn-style component primitives. No Radix dependency, no
component library — every Card / Button / Dialog / Skeleton is a small
typed wrapper around a Tailwind class set, so the design is consistent
and the bundle stays small.

**Out of scope** (deliberately): real auth (it's still a single shared
API key in localStorage), per-user state, conversation memory, query
history, dark mode, mobile-first responsive. Phase 5 candidates.

## Architecture

```
                                    Route 53
                                       │
                ┌──────────────────────┴───────────────────────┐
                ▼                                              ▼
   nlq.demos.apps.equal.expert                  api.nlq.demos.apps.equal.expert
                │                                              │
                ▼                                              ▼
    ┌──────────────────────┐                       ┌──────────────────────┐
    │ CloudFront           │                       │ API Gateway v2       │
    │ - SPA fallback       │                       │ - POST /nlq (auth)   │
    │ - security headers   │                       │ - GET /stats/* (open)│
    │ - ACM us-east-1      │                       │ - ACM eu-west-2      │
    └──────────┬───────────┘                       └──────────┬───────────┘
               │                                              │
               ▼                                              ▼
    ┌──────────────────────┐                       ┌──────────────────────┐
    │ S3 bucket            │                       │ NLQ Lambda + auth +  │
    │ cinq-nlq-spa         │                       │ NEW: stats Lambda    │
    │ (private, OAC)       │                       │                      │
    └──────────────────────┘                       └──────────┬───────────┘
                                                              │
                                                              ▼
                                                       Athena / Bedrock /
                                                         S3 Vectors
```

The SPA fetches from the API origin via plain `fetch`. CORS on the API
allows the SPA's origin via the existing `Access-Control-Allow-Origin: *`
config (sandbox-friendly; tighten in prod).

## New backend pieces

### Stats Lambda (`lambda/stats/handler.py`)

Pure stdlib + boto3 (no s3vectors needed → no bundled boto3 dance →
~5 KB zip). Routes:

| Route | Returns | Athena query |
|---|---|---|
| `GET /stats/overview` | total / accounts / types / regions / first_seen / last_seen | One aggregate over the whole view |
| `GET /stats/by-type?limit=N` | top N resource types by count | `GROUP BY resource_type` |
| `GET /stats/by-account?limit=N` | top N accounts with type/region counts | `GROUP BY account_id` |
| `GET /stats/by-region` | per-region inventory | `GROUP BY aws_region` |

In-memory cache per warm container, default 60s TTL — set via
`STATS_CACHE_TTL_SECONDS` env var. Refresh-spamming the dashboard
doesn't stack up Athena queries; the data refreshes ~daily anyway so
60s is fine.

All four routes wired into the existing API Gateway v2 HTTP API
(`api.nlq.demos.apps.equal.expert`) with **no authoriser** — they're
read-only, low-cost, and intended to be hit by the public SPA.

### CORS hardening

The HTTP API's CORS config now allows `GET, POST, OPTIONS`,
`content-type, x-api-key, authorization` headers, and exposes
`content-type, cache-control` on responses. Verified preflights work
from the SPA origin.

## Frontend

### Tech stack

| Layer | Tool | Why |
|---|---|---|
| Build | Vite 8 | Fast HMR, simple TS handling |
| Lang | TypeScript 6 | Strict types end-to-end |
| UI | React 19 | Standard |
| Styling | Tailwind v4 (`@tailwindcss/vite`) | CSS-first config via `@theme`, no PostCSS plumbing |
| State | TanStack Query v5 | Cache + retries + loading states for free |
| Charts | Recharts 3 | Solid bar/line charts that look professional out of the box |
| Icons | Lucide | Crisp single-line icons, free, enterprise look |
| Utility | clsx + tailwind-merge | shadcn-style `cn()` helper |

No Radix, no shadcn CLI. The component primitives in
`web/src/components/ui/` are hand-built so we control every line, the
bundle stays lean (~640 KB / 192 KB gzipped), and the design feels
consistent.

### Design system (`web/src/index.css`)

A single `@theme` block declares the palette and typography tokens:

- **Sidebar**: dark slate (`#0b1220`) with white text and subtle
  elevated states.
- **Content**: soft white background (`#f7f8fa`), white cards with
  light-grey borders and tiny shadows.
- **Accent**: indigo `#6366f1` (a single color the eye can lock onto).
- **Status colors**: emerald (success), amber (warning), red (danger).
- **Type**: Inter for UI, JetBrains Mono for code/SQL/identifiers,
  loaded from Google Fonts.
- **Subtle animations**: shimmer for skeletons, fade-in for content,
  spin-slow for loading icons.

Goal was "looks like a paid SaaS dashboard" rather than a hand-rolled
React app. Slate sidebar + white content with one accent + generous
whitespace + tabular numerals is the canonical enterprise look.

### Key components

| Path | What it does |
|---|---|
| `web/src/App.tsx` | Top-level state: current view, API key presence, dialog open/close |
| `web/src/components/AppShell.tsx` | Slate sidebar + brand mark + nav links + footer status |
| `web/src/components/ApiKeyDialog.tsx` | Modal for pasting the API key, persists in localStorage |
| `web/src/components/ui/{Button,Card,Badge,Skeleton,Dialog}.tsx` | Hand-built primitives |
| `web/src/views/DashboardView.tsx` | KPI cards + Recharts bar chart + freshness panel + accounts table |
| `web/src/views/QueryView.tsx` | Question textarea + tab-grouped example cards + result panel |
| `web/src/lib/api.ts` | Typed HTTP client, `ApiError` class, `getStoredApiKey()` / `setStoredApiKey()` |
| `web/src/lib/format.ts` | `fmtNumber`, `fmtMs`, `fmtTimestamp`, `truncateMiddle` |
| `web/src/lib/cn.ts` | shadcn-style `cn()` helper (clsx + tailwind-merge) |
| `web/src/data/examples.ts` | 13 curated example queries across 4 categories |

### The example library

Hardcoded as a TypeScript constant — no API call to fetch them. Each
example is `{id, category, title, question, description}`. Clicking a
card pastes the question into the textarea **and immediately fires the
API**, so the user gets results without an extra click. Categories:

- **Inventory** — histograms, account totals, tag aggregations
- **Compute** — EC2/EBS/Lambda single-resource and joined queries
- **Security** — IAM/KMS/encryption posture
- **Networking** — VPC/subnet/ENI joins

13 examples in total. Easy to edit, easy to extend.

## Hosting

### S3 + CloudFront + ACM (us-east-1)

`terraform/app/spa.tf` — 11 resources covering:

- Private S3 bucket `cinq-nlq-spa` with public access blocked
- CloudFront distribution with SPA fallback (`403/404 → /index.html`,
  status 200), HTTP/2 + HTTP/3, IPv6, gzip + brotli compression
- Custom domain `nlq.demos.apps.equal.expert`
- ACM cert in **us-east-1** via a second AWS provider alias
  `aws.us_east_1` (CloudFront refuses certs from any other region)
- Route 53 A alias record + DNS validation CNAME on the existing
  `demos.apps.equal.expert` zone
- CloudFront response headers policy: HSTS + X-Content-Type-Options +
  X-Frame-Options DENY + strict-origin-when-cross-origin Referrer-Policy
  + a CSP that allows `connect-src` to the API origin and Google Fonts
- Origin Access Control wiring the bucket policy to require requests
  signed by CloudFront

### Cache headers

The Makefile's `spa-sync` target sets cache headers per file class:

| File | `Cache-Control` |
|---|---|
| `assets/*` (immutable, content-hashed) | `public, max-age=31536000, immutable` |
| `index.html` | `no-cache, no-store, must-revalidate` |
| `favicon.svg` | `public, max-age=86400` |

So a normal redeploy only needs to invalidate `/index.html` (and the
sync handles the new hashed assets automatically), but the `spa-deploy`
target invalidates `/*` for safety.

### Build/deploy automation

| Target | What it does |
|---|---|
| `make spa-install` | `npm install` in `web/` |
| `make spa-build` | `npm run build` with `VITE_API_BASE_URL` set from terraform output |
| `make spa-dev` | `npm run dev` against the deployed API (Vite on `:5173`) |
| `make spa-sync` | Sync `web/dist/` to S3 with the right cache headers |
| `make spa-invalidate` | Issue a `/*` CloudFront invalidation |
| `make spa-deploy` | `spa-build` + `spa-sync` + `spa-invalidate` |

## Verification results

### Curl health checks

```bash
curl https://nlq.demos.apps.equal.expert/   # 200, served by CloudFront
curl https://api.nlq.demos.apps.equal.expert/stats/overview   # 200 JSON
```

CORS preflights from the SPA origin → 204 with all expected headers.

### Headless browser smoke test

Loaded `https://nlq.demos.apps.equal.expert/` in a real browser via the
Playwright MCP integration. Verified:

- Dashboard view renders with 4 KPI cards (2700 / 50 / 15 / 1), the
  top-types bar chart populated, the snapshot freshness panel showing
  the latest `last_seen_at`, and the accounts table populated.
- Sidebar nav switches between Dashboard and Query.
- API key modal accepts a key, persists to localStorage, the sidebar
  status flips from "missing" to "set".
- Query view example card click fires the request, shows the loading
  state, then renders the generated SQL, retrieved schemas, summary
  strip with timings, and the results table — all within ~7 seconds.

Screenshots in `examples/` aren't part of the repo (kept the docs
text-only so they don't go stale), but the verification was real.

## Issues encountered during build

### 1. CloudFront ACM certs must live in us-east-1

A known constraint, not a surprise — CloudFront only consumes ACM
certs from `us-east-1` no matter which region your distribution is
"in". Fix: a second AWS provider alias `aws.us_east_1`, with the
`aws_acm_certificate.spa` and `aws_acm_certificate_validation.spa`
resources both pinned to it via `provider = aws.us_east_1`. The
DNS validation records still go in the eu-west-2-managed Route 53
zone — Route 53 is a global service so the data source lookup works
fine across the provider boundary.

### 2. Recharts collapses to zero width on first paint

When the chart's container hasn't been measured yet, Recharts logs
`The width(-1) and height(-1) of chart should be greater than 0`. We
gave the wrapper an explicit `h-80` and the chart recovers as soon as
React commits the layout. Cosmetic console warning only — no visible
impact in the SPA. Worth knowing because the warning is unactionable
from the SPA side and easy to mistake for a real bug.

### 3. Tailwind v4 vs v3 syntax

Tailwind v4 (current as of 2026) uses an entirely CSS-first config
via `@theme { … }` blocks instead of a `tailwind.config.js`. Worth
catching anyone copy-pasting v3 config snippets. Vite plugin is
`@tailwindcss/vite`, not `tailwindcss/postcss`.

### 4. Vite 8 + recharts 3 + React 19 chunk size

The default JS bundle came in at ~640 KB raw / ~192 KB gzipped — Vite
warns above 500 KB raw. Fine for an internal SPA, would be worth
code-splitting for a public marketing site. Phase 5 if it matters.

### 5. The `spa-build` target needs the API URL at build time

`VITE_*` env vars are baked into the build, so `make spa-build` reads
the API endpoint from `terraform output -raw nlq_api_endpoint` at
build time and passes it as `VITE_API_BASE_URL=…`. If the API endpoint
ever changes (e.g. you re-create the API GW), you have to re-build the
SPA — there's no runtime config fetch. That's fine because terraform
output is deterministic and the endpoint is stable.

## Cost estimate (steady state)

| Component | Per month |
|---|---:|
| S3 storage (~3 MB) | ~$0.0001 |
| CloudFront (1 GB egress assumption, sandbox) | ~$0.10 |
| Route 53 zone (already existed) | $0 (shared) |
| ACM cert (us-east-1) | $0 |
| Stats Lambda (60 invocations/day, 256 MB, mostly cached) | ~$0.50 |
| **Phase 4 incremental** | **<$1/month** |

The dominant cost driver is still Bedrock inference on `/nlq`, which
phase 3 already accounted for.

## Running it

### First-time setup
```bash
# from the repo root
aws-vault exec ee-sandbox -- make deploy        # provisions everything
aws-vault exec ee-sandbox -- make spa-install   # one-off npm install
aws-vault exec ee-sandbox -- make spa-deploy    # build + sync + invalidate
open https://nlq.demos.apps.equal.expert
```

### Iterating on the SPA
```bash
# vite dev server, hot reload, fetches from the deployed API
aws-vault exec ee-sandbox -- make spa-dev
# → http://localhost:5173
```

### Re-deploying after a code change
```bash
aws-vault exec ee-sandbox -- make spa-deploy
```

### Where things live
- React source: `web/src/`
- Lambda source: `lambda/{nlq,stats,nlq_auth}/`
- Terraform: `terraform/app/{api,spa,...}.tf`
- Examples library: `web/src/data/examples.ts`

## What comes next

Phase 5 candidates:
- **Conversation memory** so users can ask follow-up questions
- **Query history** persisted per-user (DynamoDB + a session ID)
- **Streaming responses** — Bedrock streaming → API GW response
  streaming → SPA renders SQL/rows progressively
- **Result visualisation** — instead of a flat table, when the SQL
  returns 2-column aggregations the SPA could render a small chart
- **Per-user API keys** with usage tracking and quotas
- **Cognito or OIDC auth** to retire the shared API key
- **Tighten CORS** to specific origins instead of `*`
- **Deep-link example queries** so example URLs are shareable
- **Code splitting** in the SPA bundle (lazy-load Recharts and the
  Query view) to drop the initial bundle size below 200 KB
