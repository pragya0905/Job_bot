# JobPilot

A local-first job search assistant. It watches company career pages and job boards for roles matching your profile, scores each one against your actual experience using a local LLM (via [Ollama](https://ollama.com) — no cloud API, no per-call cost), and drafts a tailored resume and cover letter for the strong matches. You review, edit, and approve every draft yourself — JobPilot never auto-applies anywhere.

Runs entirely on your own machine: FastAPI + SQLite backend, server-rendered HTML dashboard, PDF resumes rendered with WeasyPrint.

## How it works

1. **Collect** — pulls postings from your company watchlist (Greenhouse, Lever, Ashby APIs) plus RemoteOK and We Work Remotely. LinkedIn/Indeed scraping exists as an opt-in, best-effort source — both sites prohibit scraping in their ToS, selectors drift over time, and it's disabled by default. Every source's health (last success, last error, consecutive failures) is tracked so a silently-broken collector doesn't just quietly return fewer jobs forever.
2. **Filter** — a cheap keyword/location pre-filter (title keywords + your location preference) trims obviously-irrelevant volume before spending any LLM time on it. Location matching is alias-aware (Bangalore/Bengaluru, Gurgaon/Gurugram, etc.) so a posting tagged with a city's official name still matches your preference.
3. **Score** — the fast local model (`gemma3:4b` by default) reads each job description against your structured profile and produces a 0–100 fit score with a short rationale, weighing your stated sector preferences as a soft signal. It also extracts a stated salary if the posting states one, and estimates one from a cited static reference table (clearly labeled unverified) if not. An optional embedding-based semantic-similarity score can run alongside it as an extra signal.
4. **Tailor** — for jobs above your score threshold, the larger local model (`gemma4:26b` by default) drafts a tailored resume (rewritten summary, reordered/re-emphasized bullets, curated skills emphasis, reverse-chronological experience order) and a tailored cover letter. See [Data fidelity](#data-fidelity) for how this is kept honest.
5. **Review** — everything lands in the dashboard: every job, its score, and a ready-to-review draft resume side by side with the JD. Edit inline, regenerate (non-blocking — a live "Generating..." indicator polls until it's done), download/view the resume and cover letter PDFs, mark applied, leave notes — all in your own words, on your own schedule.

## Requirements

- macOS (developed/tested on Apple Silicon; WeasyPrint's native deps below are Homebrew-specific)
- Python 3.11+
- [Ollama](https://ollama.com) installed and running locally, with a scoring model and a tailoring model pulled:
  ```
  ollama pull gemma3:4b
  ollama pull gemma4:26b   # or any other model — see Configuration
  ollama pull nomic-embed-text   # optional, only needed for semantic scoring
  ```

## Setup

```bash
# Native deps for WeasyPrint (PDF rendering) — pip alone can't install these
brew install pango cairo gdk-pixbuf libffi

# Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Config
cp config.example.yaml config.yaml   # already gitignored, edit as needed
```

### Apple Silicon note

WeasyPrint sometimes can't locate its native libraries via the default dylib search path. `jobpilot/pdf/render.py` sets `DYLD_LIBRARY_PATH` automatically before importing WeasyPrint, so this should work out of the box — no shell setup needed.

## Running it

```bash
source .venv/bin/activate
uvicorn jobpilot.main:app --reload
```

Open `http://127.0.0.1:8000`, sign up, and fill in your profile.

The server binds to `127.0.0.1` only and is designed for local, single-machine use.

### CLI

Scans can also be triggered without the browser:

```bash
python -m jobpilot.cli run-scan --email you@example.com
python -m jobpilot.cli list-jobs --email you@example.com --min-score 70
```

## Using it

- **Profile** (`/profile`) — the source of truth for your resume content: basics, categorized skills, experience, internships, projects, education (with CGPA and relevant coursework), certifications. Tailoring only ever reorders/re-emphasizes what's here; it never invents anything. Each experience/internship entry can either be hand-written (verbatim bullets, never reworded) or use **constrained-rewrite mode**: describe what you did once in plain text, set how many bullets you want, and JobPilot rewrites it into job-tailored bullets per application — with a guardrail that drops any bullet containing a number that isn't traceable back to what you wrote.
- **Companies** (`/companies`) — your watchlist of companies to poll via their Greenhouse/Lever/Ashby job board APIs. Per-user — each account has its own list.
- **Preferences** (`/preferences`) — location mode (specific locations, remote-only, or anywhere) with an autocomplete chip input for picking cities, sector priorities (soft signal fed into scoring, not a hard filter), the auto-tailor score threshold, and the semantic-scoring opt-in.
- **Scan** (`/scan`) — manually triggered; no background scheduler. Shows live stage/progress, a full permanent per-line log (searchable, never capped), and CPU/memory/Ollama-model usage while it runs. Per-source collector health is shown alongside it.
- **Jobs** (`/jobs`) — every collected job, filterable by score, status, application state, source, location, remote-only, stale-only, and free-text search; sortable by score or date collected. Shows stated/estimated salary inline. Bulk-select and delete, or change application status inline. Jobs not re-seen in a scan for a while (configurable, default 14 days) are flagged stale.
- **Job detail** (`/jobs/{id}`) — score rationale, matched/missing skills, JD, and the tailored draft side by side. Edit any field, regenerate with AI (runs in the background with a live progress indicator — no more waiting on a blocked page), view/download the resume and cover letter PDFs, mark applied, leave notes, and see the full scoring/tailoring activity log for that specific job.
- **System** (`/monitor`) — live CPU, memory, and currently-loaded Ollama model status, independent of any scan.
- **Export** (`/export`, linked from Profile) — download every job, score, application timeline, and tailored draft as a single JSON file.

## Configuration

`config.yaml` (copied from `config.example.yaml`, gitignored) holds settings shared across the whole local install — not per-user:

```yaml
database_path: "data/jobpilot.db"
resume_dir: "data/resumes"
stale_after_days: 14        # how long since last-seen before a job is flagged stale

sources:
  remoteok: { enabled: true }
  weworkremotely: { enabled: true }
  linkedin: { enabled: false }   # best-effort, fragile — see note above
  indeed: { enabled: false }

filters:
  title_keywords: [...]   # pre-filter: title must contain one of these
  locations: [...]        # fallback location list if a user hasn't set preferences

scoring:
  model: "gemma3:4b"
  temperature: 0.0

tailoring:
  score_threshold: 75     # default minimum score to auto-generate a tailored draft
  model: "gemma4:26b"
  temperature: 0.2

ollama:
  host: "http://localhost:11434"

embedding:
  model: "nomic-embed-text"   # only used if a user opts into semantic scoring
```

Per-user settings (profile, company watchlist, location/sector preferences, score threshold, semantic scoring toggle) live in the database and are managed through the app itself, not this file.

### Choosing models

Any Ollama model works for `scoring.model` / `tailoring.model`. The split exists because scoring runs once per collected job (many calls, needs to be fast) while tailoring runs only for strong matches (fewer calls, worth spending more compute on). If your tailoring model supports "thinking" mode, make sure it doesn't burn its whole token budget on chain-of-thought before producing output — see `jobpilot/llm/client.py` (`think=False` is passed explicitly for this reason).

## Data fidelity

Local models — especially smaller/quantized ones — will occasionally corrupt a word, invent a plausible-sounding detail, or silently drop content they judge "irrelevant." Because this output becomes your actual resume, JobPilot treats the model as a *curator*, not a source of truth, wherever accuracy matters more than phrasing:

- **Company / title / location / dates** on each tailored role are copied verbatim from your profile — the model can never alter them, only choose whether an entry appears and in what order.
- **Bullets** (verbatim mode) are matched back to your original bullet text by similarity and the original is used regardless of what the model returned — so a model rewording or corrupting a bullet can't change what actually ends up on the page.
- **Bullets** (constrained-rewrite mode) may be freely reworded from your raw description, but any generated bullet containing a number that isn't traceable back to your original text is dropped — the model can rephrase and re-emphasize, but can't invent a metric.
- **Every experience and internship entry** in your profile is force-included in the tailored output, in reverse-chronological order; the model can select which bullets to show, but can't make a whole role disappear or reorder roles out of date order.
- **Skill category names** are matched back to your real categories; an invented category (or one with commentary baked into the name) is dropped rather than shown.
- **Stated salary** extracted from a job description is validated in Python after the fact (digit-presence check, sentinel-string check, a blocklist for common false positives like 401(k) matching) before being trusted.
- **Estimated compensation** (shown only when a posting states no salary of its own) is never LLM-generated. The model only classifies a job into a role/seniority/location bucket; the actual number comes from a static, hand-sourced reference table with inline citations (`jobpilot/pipeline/COMP_REFERENCE_SOURCES.md`), always rendered with an "estimated, unverified" label.
- **Cover letters** get the same anti-fabrication instruction as resume bullets, plus a structural strip of any greeting/sign-off the model adds despite being told not to (the rendered letter already adds its own).

None of this is theoretical — every one of these was a real failure observed in testing and is why the guardrail exists. Review your drafts before applying regardless; local models are good, not infallible.

## Project layout

```
jobpilot/
  auth.py, db.py, config.py, date_utils.py, system_info.py, text_utils.py
  models/               # SQLModel tables — User, Profile*, Job, JobScore, ResumeDraft,
                         #   CompanyWatch, JobPreference, ScanRun, ScanLogEntry,
                         #   SourceHealth, ApplicationStatus, ApplicationEvent
  sources/               # one collector per job source (greenhouse, lever, ashby,
                         #   remoteok, weworkremotely, linkedin, indeed)
  pipeline/              # collect -> filter -> score -> tailor, plus scan progress
                         #   logging, source health tracking, and compensation
                         #   classification/reference-table lookup
  llm/                   # Ollama client wrapper (structured output, retries),
                         #   embeddings helper, and all prompts
  schemas/               # Pydantic schemas for LLM structured output
  pdf/                   # Jinja2 + WeasyPrint resume/cover-letter rendering
  web/routes/            # FastAPI routers (auth, profile, companies, preferences,
                         #   jobs, scan, dashboard, monitor, export)
  web/templates/         # Jinja2 + HTMX + Alpine.js + Tailwind (all via CDN, no build step)
  cli.py
```

## Known limitations

- LinkedIn/Indeed collection is best-effort and will break periodically as those sites change their markup — it's off by default for a reason.
- Local model inference speed depends entirely on your hardware; tailoring a resume can take anywhere from ~30 seconds to several minutes per job depending on the model and machine. Regeneration runs in the background with a live progress indicator rather than blocking the page.
- Estimated compensation is a rough band from a small, manually-researched reference table (see the citations doc) — not live market data, and only covers a limited set of role families/locations.
- No automated migrations — schema changes to existing tables during development were applied with manual `ALTER TABLE` statements. Fine for a personal local install; would need a real migration tool (Alembic) before any multi-instance or production use.
