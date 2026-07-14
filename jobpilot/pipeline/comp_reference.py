"""Static, hand-curated compensation reference table for `estimated_comp`.

This is NOT live data and the LLM never generates these numbers — the
pipeline can only run local models with no web access, so asking it to
"estimate market rate" from parametric memory would be an ungrounded guess
dressed up as a fact, which is exactly what this app avoids everywhere else
(bullet verification, skill reconciliation, stated_salary extraction). The
number always comes from this table; the LLM's only job (see
pipeline/comp_classify.py) is classifying a job posting into one of the
buckets below — a task closer to the scoring/matching it's already used for.

Every band here was researched against public salary-survey sites in
July 2026 and is source-cited below. See COMP_REFERENCE_SOURCES.md in this
same directory for the full per-source methodology notes, confidence
caveats, and cross-check details — this file only carries the short form.
This data goes stale; it should be re-researched periodically (comp moves
year over year) rather than trusted indefinitely.
"""

from typing import NamedTuple

ROLE_FAMILIES = ["backend", "frontend", "fullstack", "devops_sre", "data_ml", "mobile", "qa"]
SENIORITY_LEVELS = ["junior", "mid", "senior"]  # ~0-2yr / ~2-5yr / ~5-8+yr
LOCATION_BUCKETS = ["india_tier1", "us_remote", "other"]  # india_tier1 = Hyderabad/Bangalore/Pune-class hubs


class CompBand(NamedTuple):
    range: str
    source: str
    as_of: str
    confidence: str  # see COMP_REFERENCE_SOURCES.md for what each level means


# (role_family, seniority_level, location_bucket) -> CompBand.
# "other" location_bucket has no entries anywhere in this table on purpose —
# a job that doesn't classify into a hub we actually researched gets no
# estimate rather than a number borrowed from a different market.
COMP_REFERENCE_TABLE: dict[tuple[str, str, str], CompBand] = {
    # --- India tier-1 (Hyderabad / Bangalore / Pune) — LPA (lakhs/year) ---
    # Primary shape: Omnivoo 2026 salary guides (editorial, no disclosed
    # survey methodology — confidence "editorial"). Corroborated as a
    # plausible floor by PayScale India's disclosed-sample-size averages,
    # which run conservative due to a service-sector-skewed respondent pool.
    ("backend", "junior", "india_tier1"): CompBand(
        "₹6-12 LPA", "Omnivoo Backend Developer Salary Guide 2026, corroborated by PayScale India "
        "(Software Engineer, n=3,846 early-career)", "Apr-May 2026", "editorial_corroborated"
    ),
    ("backend", "mid", "india_tier1"): CompBand(
        "₹12-22 LPA", "Omnivoo Backend Developer Salary Guide 2026", "Apr 2026", "editorial"
    ),
    ("backend", "senior", "india_tier1"): CompBand(
        "₹22-40 LPA", "Omnivoo Backend Developer Salary Guide 2026, corroborated by PayScale India "
        "(Senior Software Engineer, n=4,547, overall avg ₹16.4L)", "Apr-May 2026", "editorial_corroborated"
    ),
    ("frontend", "junior", "india_tier1"): CompBand(
        "₹5-10 LPA", "Omnivoo Frontend Developer Salary Guide 2026", "Apr 2026", "editorial"
    ),
    ("frontend", "mid", "india_tier1"): CompBand(
        "₹10-18 LPA", "Omnivoo Frontend Developer Salary Guide 2026", "Apr 2026", "editorial"
    ),
    ("frontend", "senior", "india_tier1"): CompBand(
        "₹18-32 LPA", "Omnivoo Frontend Developer Salary Guide 2026 (city breakdown: Bengaluru ₹20-34L, "
        "Hyderabad ₹19-32L, Pune ₹17-28L)", "Apr 2026", "editorial"
    ),
    # Fullstack has no dedicated survey — derived as a backend-leaning blend
    # of the backend/frontend rows above. PayScale's own numbers support a
    # backend-leaning blend: Full Stack Software Engineer overall avg ₹7.90L
    # sits close to Backend/SWE early-career (₹7.54L) and above Web
    # Developer early-career (₹4.04L).
    ("fullstack", "junior", "india_tier1"): CompBand(
        "₹6-11 LPA", "Derived: backend/frontend blend (backend-leaning per PayScale India cross-check)",
        "Apr-May 2026", "derived"
    ),
    ("fullstack", "mid", "india_tier1"): CompBand(
        "₹11-20 LPA", "Derived: backend/frontend blend (backend-leaning per PayScale India cross-check)",
        "Apr-May 2026", "derived"
    ),
    ("fullstack", "senior", "india_tier1"): CompBand(
        "₹20-36 LPA", "Derived: backend/frontend blend; corroborated by Omnivoo Full Stack Developer "
        "Salary Guide 2026 senior/product-co figure of ₹30-50 LPA CTC", "Apr-May 2026", "derived_corroborated"
    ),
    ("devops_sre", "junior", "india_tier1"): CompBand(
        "₹5-9 LPA", "Omnivoo DevOps Engineer Salary Guide 2026, corroborated by PayScale India "
        "(DevOps Engineer, n=978, entry avg ₹4.5L)", "Apr-May 2026", "editorial_corroborated"
    ),
    ("devops_sre", "mid", "india_tier1"): CompBand(
        "₹10-20 LPA", "Omnivoo DevOps Engineer Salary Guide 2026, corroborated by Glassdoor India "
        "DevOps Engineer (n=14,850, 25th-75th pctile ₹5.5-13.5L)", "Apr 2026", "editorial_corroborated"
    ),
    ("devops_sre", "senior", "india_tier1"): CompBand(
        "₹20-35 LPA", "Omnivoo DevOps Engineer Salary Guide 2026, corroborated by Glassdoor India "
        "(90th pctile ₹20L)", "Apr 2026", "editorial_corroborated"
    ),
    ("data_ml", "junior", "india_tier1"): CompBand(
        "₹6-10 LPA", "Omnivoo Data Scientist Salary Guide 2026, corroborated by PayScale India "
        "(Data Scientist, n=307 entry)", "Apr-May 2026", "editorial_corroborated"
    ),
    ("data_ml", "mid", "india_tier1"): CompBand(
        "₹12-22 LPA", "Omnivoo Data Scientist Salary Guide 2026, corroborated by PayScale India "
        "(n=807 early-career, avg ₹10.1L)", "Apr-May 2026", "editorial_corroborated"
    ),
    ("data_ml", "senior", "india_tier1"): CompBand(
        "₹22-40 LPA", "Omnivoo Data Scientist Salary Guide 2026", "Apr 2026", "editorial"
    ),
    ("mobile", "junior", "india_tier1"): CompBand(
        "₹5-9 LPA", "Omnivoo Mobile Developer Salary Guide 2026", "Apr 2026", "editorial"
    ),
    ("mobile", "mid", "india_tier1"): CompBand(
        "₹10-22 LPA", "Omnivoo Mobile Developer Salary Guide 2026 (notes iOS commands ~10-15% premium "
        "over Android)", "Apr 2026", "editorial"
    ),
    ("mobile", "senior", "india_tier1"): CompBand(
        "₹22-38 LPA", "Omnivoo Mobile Developer Salary Guide 2026", "Apr 2026", "editorial"
    ),
    ("qa", "junior", "india_tier1"): CompBand(
        "₹4-7 LPA", "Omnivoo QA Engineer Salary Guide 2026, corroborated by PayScale India "
        "(QA Engineer, n=633, overall avg ₹5.5L)", "Apr-May 2026", "editorial_corroborated"
    ),
    ("qa", "mid", "india_tier1"): CompBand(
        "₹8-16 LPA", "Omnivoo QA Engineer Salary Guide 2026", "Apr 2026", "editorial"
    ),
    ("qa", "senior", "india_tier1"): CompBand(
        "₹16-28 LPA", "Omnivoo QA Engineer Salary Guide 2026, corroborated by Glassdoor Senior "
        "Automation QA Engineer/SDET Bangalore (25th-75th pctile ₹20.75-32L)", "2026", "editorial_corroborated"
    ),
    # --- US remote — USD/year, base-leaning (not total comp) ---
    # Backend and DevOps are cross-checked across 3+ independent sources
    # (Levels.fyi, Glassdoor, BLS OEWS, Payscale). Data/ML has one strong
    # primary source without independent cross-check. Frontend has the
    # weakest coverage — no primary source published a clean mid/senior
    # split, so this uses Levels.fyi's aggregate percentile spread as a
    # proxy (25th pct ~ mid, 75th-90th pct ~ senior). No mobile/qa rows for
    # this bucket — no adequate sourced data was found for either.
    ("backend", "mid", "us_remote"): CompBand(
        "$120k-$180k", "Levels.fyi Software Engineer (25th-75th pctile), corroborated by Glassdoor "
        "Remote Software Engineer (25th-75th pctile ~$116-187k, n~12,000) and BLS OEWS 15-1252",
        "Jul 2026 (BLS: May 2024)", "cross_checked"
    ),
    ("backend", "senior", "us_remote"): CompBand(
        "$150k-$230k", "Levels.fyi Software Engineer (75th-90th pctile), corroborated by Payscale "
        "Senior Software Engineer (n=13,938, base range $102-183k)", "Jul 2026 (Payscale: May 2026)",
        "cross_checked"
    ),
    ("devops_sre", "mid", "us_remote"): CompBand(
        "$115k-$175k", "Levels.fyi DevOps Engineer (25th-75th pctile), corroborated by Glassdoor "
        "US DevOps Engineer (n=16,493, avg total pay $137,883)", "Jul 2026 (Glassdoor: Jun 2025)",
        "cross_checked"
    ),
    ("devops_sre", "senior", "us_remote"): CompBand(
        "$150k-$210k", "Levels.fyi DevOps Engineer (75th-90th pctile), corroborated by Glassdoor "
        "Senior DevOps Engineer (avg $181,507)", "2025-2026", "cross_checked"
    ),
    ("data_ml", "mid", "us_remote"): CompBand(
        "$150k-$200k", "Levels.fyi Data Scientist (ML focus, avg total comp $180k) — single strong "
        "primary source, not independently cross-checked", "2025-2026", "single_primary"
    ),
    ("data_ml", "senior", "us_remote"): CompBand(
        "$200k-$300k", "Levels.fyi Machine Learning Engineer (25th-75th pctile of a $272.5k median), "
        "corroborated by Glassdoor Senior Data Scientist (avg $233,206)", "Jul 2026", "cross_checked"
    ),
    ("frontend", "mid", "us_remote"): CompBand(
        "$100k-$150k", "Levels.fyi Frontend Software Engineer (proxy: 25th pctile of aggregate spread, "
        "no primary source publishes a clean mid/senior split for this title)", "Jul 2026", "weak_proxy"
    ),
    ("frontend", "senior", "us_remote"): CompBand(
        "$150k-$220k", "Levels.fyi Frontend Software Engineer (proxy: 75th-90th pctile of aggregate "
        "spread, no primary source publishes a clean mid/senior split)", "Jul 2026", "weak_proxy"
    ),
}


def lookup_comp_band(role_family: str, seniority_level: str, location_bucket: str) -> CompBand | None:
    return COMP_REFERENCE_TABLE.get((role_family, seniority_level, location_bucket))
