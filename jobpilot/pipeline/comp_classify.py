import logging

from jobpilot.llm.client import structured_chat
from jobpilot.pipeline.comp_reference import LOCATION_BUCKETS, ROLE_FAMILIES, SENIORITY_LEVELS, lookup_comp_band
from jobpilot.schemas.llm import CompClassificationOut

logger = logging.getLogger("jobpilot.comp_classify")

COMP_CLASSIFY_SYSTEM = f"""You are classifying a job posting into fixed categories for a \
compensation lookup table — you are NOT estimating a salary number yourself, only picking which \
pre-defined bucket this posting belongs to.

"role_family" must be exactly one of: {", ".join(ROLE_FAMILIES)}.
Pick "fullstack" only if the posting explicitly asks for both frontend and backend work. If \
nothing else fits well, pick the closest match from the list (e.g. a generic "Software Engineer" \
posting with no specialization stated is usually "backend").

"seniority_level" must be exactly one of: {", ".join(SENIORITY_LEVELS)}.
"junior" = 0-2 years / entry-level / associate. "mid" = roughly 2-5 years, no seniority qualifier \
or "II"/"2" in the title. "senior" = "senior"/"staff"/"principal"/"lead" in the title, or 5+ years \
required.

"location_bucket" must be exactly one of: {", ".join(LOCATION_BUCKETS)}.
"india_tier1" = Hyderabad, Bangalore/Bengaluru, Pune, Mumbai, Delhi/NCR, Gurgaon, Noida, Chennai, \
Kolkata, or unspecified-but-clearly-Indian. "us_remote" = the posting is remote and scoped to the \
US (explicitly US-only, or a US company/US salary figures with no other country mentioned). \
"other" = anything else, including remote-anywhere with no country scoping, or a location you're \
not confident falls in the other two buckets — when unsure, use "other" rather than guessing."""


def build_classify_prompt(job_title: str, company_name: str, location: str, description: str) -> str:
    return (
        f"JOB:\nTitle: {job_title}\nCompany: {company_name}\nLocation: {location}\n\n"
        f"DESCRIPTION:\n{description[:3000]}"
    )


async def estimate_compensation(
    *, host: str, model: str, job_title: str, company_name: str, location: str, description: str
) -> str | None:
    """Classify a job into (role_family, seniority_level, location_bucket)
    and look up the corresponding band in the static reference table.
    Returns None whenever the classification doesn't land on a bucket the
    table actually has data for — a deliberate fail-closed design, since
    showing no estimate is always safer than showing a number for the wrong
    bucket. Never invokes the model to produce the number itself.
    """
    result = await structured_chat(
        host=host,
        model=model,
        system=COMP_CLASSIFY_SYSTEM,
        user=build_classify_prompt(job_title, company_name, location, description),
        schema=CompClassificationOut,
        temperature=0.0,
        max_output_tokens=200,
    )
    if result is None:
        return None

    role_family = result.role_family.strip().lower()
    seniority_level = result.seniority_level.strip().lower()
    location_bucket = result.location_bucket.strip().lower()

    if role_family not in ROLE_FAMILIES or seniority_level not in SENIORITY_LEVELS or location_bucket not in LOCATION_BUCKETS:
        logger.info(
            "comp classification landed outside known buckets (role=%r level=%r location=%r) — no estimate",
            role_family, seniority_level, location_bucket,
        )
        return None

    band = lookup_comp_band(role_family, seniority_level, location_bucket)
    return band.range if band else None
