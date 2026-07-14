# `estimated_comp` reference data — sources and methodology

This documents where every number in `comp_reference.py` actually came from.
It exists because `estimated_comp` is a **static, hand-curated table**, not a
live lookup — the app's LLM pipeline runs entirely on local Ollama models
with no web access, so there was no way to fetch this at runtime without
either (a) adding a paid search API, which contradicts this project's
no-internet-dependency / no-API-cost design from day one, or (b) asking the
local model to invent a number from its own training data, which is an
ungrounded guess with nothing behind it. Neither was acceptable, so the
numbers were researched once (July 2026), checked into the repo as data, and
the LLM's only role at runtime is *classifying* a job posting into one of
these buckets — never generating the number itself.

**This data will go stale.** Compensation moves year over year; treat
anything more than ~12 months old as due for a re-check. There's no
freshness enforcement — a future maintainer (or you, six months from now)
needs to consciously decide to re-run the research and update the table.

## Confidence levels used in the table

- `cross_checked` — 2+ independent primary sources (disclosed sample sizes
  or government survey) agree within a reasonable range.
- `editorial_corroborated` — primary shape from an editorial salary guide
  (no disclosed survey methodology) with a disclosed-sample-size source used
  as a plausible floor/sanity-check.
- `editorial` — editorial salary guide only, no independent corroboration
  found. Directional, not survey-grade.
- `single_primary` — one disclosed-methodology source, no second source
  found to cross-check against.
- `derived` — no dedicated source exists for this exact role family;
  interpolated from adjacent rows with the reasoning noted inline.
- `weak_proxy` — no source published data banded the way this table needs
  it (e.g. no clean mid/senior split), so an aggregate percentile spread is
  used as a stand-in. Treat as the least reliable tier still worth showing.

## India tier-1 (Hyderabad / Bangalore / Pune) — sources

Primary shape for most rows: **Omnivoo** 2026 role-specific salary guides
(backend, frontend, devops, data scientist, mobile, QA — each published as
`omnivoo.com/blog/{role}-salary-india-2026`, dated April 2026). These are
editorial guides with clean junior/mid/senior experience bands matching what
this table needs, but **Omnivoo does not disclose a survey methodology or
sample size** — treat as directional, not a verified aggregate.

Corroboration source: **PayScale India** (`payscale.com/research/IN/Job=...`),
which does disclose sample sizes per title (n ranging from ~100 to ~4,500+
self-reported salaries), pulled May 2026. PayScale India's numbers run
**systematically lower** than Omnivoo/Glassdoor/AmbitionBox at every
experience band — its respondent pool skews toward smaller/service-sector
companies rather than product companies, which is where this app's target
roles (SDE/backend/product engineering) more often land. It's used here as a
lower-bound sanity check, not as the primary figure, given that skew.

Additional single-point corroboration used for specific rows: Glassdoor
India DevOps Engineer (n=14,850, accessed via search snippet — the live
Glassdoor page returned HTTP 403 to a direct fetch, so this figure is
secondhand from a search-result summary, not independently re-verified) and
Glassdoor Senior Automation QA Engineer/SDET, Bangalore.

**Explicitly excluded**: AmbitionBox and 6figr numbers were found during
research but could not be directly fetched (AmbitionBox timed out on 5
separate URL attempts, likely bot-blocked; 6figr is JS-rendered and returned
only a page shell). Their figures only exist as Google search-summary
snippets of those pages, which wasn't a high enough confidence bar to cite
directly — they're mentioned in the research notes but don't appear in the
table.

**Fullstack has no dedicated source.** No salary guide was found that
surveys "full stack developer" as its own category with a clean experience
band. The table's fullstack rows are a backend-leaning interpolation between
the backend and frontend rows, justified by PayScale India's own numbers:
Full Stack Software Engineer overall avg (₹7.90L) sits much closer to
Backend/Software Engineer early-career (₹7.54L) than to Web Developer
early-career (₹4.04L) — i.e., a backend-leaning blend is what PayScale's own
data implies, even without a dedicated fullstack survey.

## US remote — sources

Primary sources: **Levels.fyi** (percentile bands by title, tech-company-
skewed — these are compensation packages at companies that report to
Levels.fyi, which trends toward well-funded tech companies, not the market
median), **Glassdoor** (broader market, includes remote-specific listings),
**BLS OEWS** (SOC 15-1252 "Software Developers" — a US government wage
survey, May 2024 reference period, the most representative-of-the-broad-
market source used but also the least current), and **Payscale**
(years-of-experience-banded pages).

- **Backend/general SWE**: cross-checked across all four sources above —
  the best-covered role family in this table.
- **DevOps/SRE**: cross-checked across Levels.fyi, Glassdoor, and Payscale.
- **Data Scientist/ML Engineer**: Levels.fyi only (Machine Learning
  Engineer title, median $272.5k) with Glassdoor Senior Data Scientist
  ($233k avg) as a single corroboration point — no independent second
  primary source was found.
- **Frontend**: the weakest US-remote row. No primary source published a
  clean mid/senior experience split for this title — Payscale only had
  entry/early-career bands, Levels.fyi only publishes an aggregate
  percentile spread. The table's mid/senior rows use that aggregate
  spread's 25th and 75th-90th percentiles as a stand-in (`weak_proxy`
  confidence) rather than a true experience-banded figure.
- **No mobile or QA rows for US remote** — research did not cover these
  role families for the US bucket (out of scope for the initial pass,
  since India tier-1 is this app's primary target market); a job that
  classifies into either shows no estimate rather than a fabricated one.

## What's deliberately NOT in this table

- Any location outside India tier-1 hubs and US remote (`location_bucket
  = "other"`) — no rows exist for this bucket on purpose, so a job that
  doesn't classify into a researched hub shows no estimate rather than a
  number borrowed from an unrelated market.
- Staff/Principal-level bands — public salary-survey coverage at that level
  is thin and highly company-specific; folding it into "senior" would have
  meant either a misleadingly narrow range or an uncomfortably wide one.

## Regenerating this table

There's no automated refresh — re-research is a manual process:
1. Re-run the same category of search (site-specific salary aggregators,
   filtered to the specific role/experience-band/location) for each row.
2. Prefer sources that disclose a sample size or survey methodology over
   single-anecdote or methodology-free editorial pages.
3. Update the `as_of` and `source` fields per row, and bump the "researched"
   date at the top of `comp_reference.py`'s docstring.
4. Keep the confidence labels honest — if a re-check only turns up an
   editorial source with no corroboration, mark it `editorial`, not
   `cross_checked`.
