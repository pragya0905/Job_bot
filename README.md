# JobPilot

A local-first job search assistant. It watches company career pages and job boards for roles matching your profile, scores each one against your actual experience using a local LLM (via [Ollama](https://ollama.com) — no cloud API, no per-call cost), and drafts a tailored resume for the strong matches. You review, edit, and approve every draft yourself — JobPilot never auto-applies anywhere.

Runs entirely on your own machine: FastAPI + SQLite backend, server-rendered HTML dashboard, PDF resumes rendered with WeasyPrint.

## How it works

1. **Collect** — pulls postings from your company watchlist (Greenhouse, Lever, Ashby APIs) plus RemoteOK and We Work Remotely. LinkedIn/Indeed scraping exists as an opt-in, best-effort source — both sites prohibit scraping in their ToS, selectors drift over time, and it's disabled by default.
2. **Filter** — a cheap keyword/location pre-filter (title keywords + your location preference) trims obviously-irrelevant volume before spending any LLM time on it.
3. **Score** — the fast local model (`gemma3:4b` by default) reads each job description against your structured profile and produces a 0–100 fit score with a short rationale, weighing your stated sector preferences as a soft signal.
4. **Tailor** — for jobs above your score threshold, the larger local model (`gemma4:26b` by default) drafts a tailored resume: rewritten summary, reordered bullets, curated skills emphasis. See [Data fidelity](#data-fidelity) for how this is kept honest.
5. **Review** — everything lands in the dashboard: every job, its score, and a ready-to-review draft resume side by side with the JD. Edit inline, regenerate, download/view the PDF, mark applied — all in your own words, on your own schedule.

## Requirements

- macOS (developed/tested on Apple Silicon; WeasyPrint's native deps below are Homebrew-specific)
- Python 3.11+
- [Ollama](https://ollama.com) installed and running locally, with a scoring model and a tailoring model pulled:
  ```
  ollama pull gemma3:4b
  ollama pull gemma4:26b   # or any other model — see Configuration
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

- **Profile** (`/profile`) — the source of truth for your resume content: basics, categorized skills, experience, internships, projects, education, certifications. Tailoring only ever reorders/re-emphasizes what's here; it never invents anything.
- **Companies** (`/companies`) — your watchlist of companies to poll via their Greenhouse/Lever/Ashby job board APIs. Per-user — each account has its own list.
- **Preferences** (`/preferences`) — location mode (specific locations, remote-only, or anywhere) and sector priorities (soft signal fed into scoring, not a hard filter).
- **Scan** (`/scan`) — manually triggered; no background scheduler. Shows live stage/progress, a scrolling log, and CPU/memory/Ollama-model usage while it runs.
- **Jobs** (`/jobs`) — every collected job, filterable by score, status, application state, source, location, remote-only, and free-text search. Bulk-select and delete, or change application status inline.
- **Job detail** (`/jobs/{id}`) — score rationale, JD, and the tailored draft side by side. Edit any field, regenerate with AI, view the PDF inline, or download it (named `{YourName}_Resume.pdf`).
- **System** (`/monitor`) — live CPU, memory, and currently-loaded Ollama model status, independent of any scan.

## Configuration

`config.yaml` (copied from `config.example.yaml`, gitignored) holds settings shared across the whole local install — not per-user:

```yaml
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
  score_threshold: 75     # minimum score to auto-generate a tailored draft
  model: "gemma4:26b"
  temperature: 0.2

ollama:
  host: "http://localhost:11434"
```

Per-user settings (profile, company watchlist, location/sector preferences) live in the database and are managed through the app itself, not this file.

### Choosing models

Any Ollama model works for `scoring.model` / `tailoring.model`. The split exists because scoring runs once per collected job (many calls, needs to be fast) while tailoring runs only for strong matches (fewer calls, worth spending more compute on). If your tailoring model supports "thinking" mode, make sure it doesn't burn its whole token budget on chain-of-thought before producing output — see `jobpilot/llm/client.py` (`think=False` is passed explicitly for this reason).

## Data fidelity

Local models — especially smaller/quantized ones — will occasionally corrupt a word, invent a plausible-sounding detail, or silently drop content they judge "irrelevant." Because this output becomes your actual resume, JobPilot treats the model as a *curator*, not a source of truth, wherever accuracy matters more than phrasing:

- **Company / title / location / dates** on each tailored role are copied verbatim from your profile — the model can never alter them, only choose whether an entry appears and in what order.
- **Bullets** are matched back to your original bullet text by similarity and the verbatim original is used, regardless of what the model returned — so a model rewording or corrupting a bullet can't change what actually ends up on the page.
- **Every experience and internship entry** in your profile is force-included in the tailored output; the model can reorder entries and select which bullets to show, but can't make a whole role disappear.
- **Skill category names** are matched back to your real categories; an invented category (or one with commentary baked into the name) is dropped rather than shown.

None of this is theoretical — every one of these was a real failure observed in testing and is why the guardrail exists. Review your drafts before applying regardless; local models are good, not infallible.

## Project layout

```
jobpilot/
  auth.py, db.py, config.py, system_info.py, text_utils.py
  models/              # SQLModel tables (User, Profile*, Job, JobScore, ResumeDraft,
                        #   CompanyWatch, JobPreference, ScanRun, ApplicationStatus)
  sources/             # one collector per job source (greenhouse, lever, ashby,
                        #   remoteok, weworkremotely, linkedin, indeed)
  pipeline/            # collect -> filter -> score -> tailor, plus scan progress logging
  llm/                 # Ollama client wrapper (structured output, retries) + prompts
  schemas/             # Pydantic schemas for LLM structured output
  pdf/                 # Jinja2 + WeasyPrint resume rendering
  web/routes/          # FastAPI routers (auth, profile, companies, preferences,
                        #   jobs, scan, dashboard, monitor)
  web/templates/        # Jinja2 + HTMX + Tailwind (CDN, no build step)
  cli.py
```

## Known limitations

- LinkedIn/Indeed collection is best-effort and will break periodically as those sites change their markup — it's off by default for a reason.
- Local model inference speed depends entirely on your hardware; tailoring a resume can take anywhere from ~30 seconds to several minutes per job depending on the model and machine.
- No automated migrations — schema changes to existing tables during development were applied with manual `ALTER TABLE` statements. Fine for a personal local install; would need a real migration tool (Alembic) before any multi-instance or production use.
