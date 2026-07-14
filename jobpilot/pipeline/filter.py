from jobpilot.config import FiltersConfig
from jobpilot.models import JobPreference
from jobpilot.sources.base import RawJob


def passes_filters(job: RawJob, filters: FiltersConfig, preference: JobPreference | None = None) -> bool:
    title = job.title.lower()
    if filters.title_keywords and not any(kw.lower() in title for kw in filters.title_keywords):
        return False

    return _passes_location(job, filters, preference)


def _passes_location(job: RawJob, filters: FiltersConfig, preference: JobPreference | None) -> bool:
    if preference is not None:
        if preference.location_mode == "any":
            return True
        if preference.location_mode == "remote_only":
            return job.is_remote
        if preference.location_mode == "specific_or_remote" and preference.preferred_locations:
            # The mode name is a promise: remote always passes here regardless
            # of whether the user separately typed "Remote" into their list.
            return job.is_remote or _location_matches(job, preference.preferred_locations)

    # No preference set (or default mode with no locations configured yet) —
    # fall back to the shared config.yaml locations list.
    if not filters.locations:
        return True
    return _location_matches(job, filters.locations)


# Job postings/scrapers commonly use a city's official or alternate name
# rather than the one on /preferences — LinkedIn/Indeed tag Bangalore
# postings "Bengaluru" and Gurgaon postings "Gurugram" far more often than
# not, and a plain substring match against only the literal string the user
# picked silently drops every one of those postings (confirmed against real
# scan data: LinkedIn searched Hyderabad/Bangalore/Pune/Gurgaon and returned
# 180 postings, but zero ever reached storage tagged Bangalore or Gurgaon —
# only Hyderabad/Pune, whose scraped strings happen to literally contain
# the same words the user picked). Applies uniformly to any city, including
# ones typed into the free-text "Other locations" field, not just this list.
_CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "bangalore": ("bengaluru",),
    "bengaluru": ("bangalore",),
    "gurgaon": ("gurugram",),
    "gurugram": ("gurgaon",),
    "mumbai": ("bombay",),
    "bombay": ("mumbai",),
    "kolkata": ("calcutta",),
    "calcutta": ("kolkata",),
    "chennai": ("madras",),
    "madras": ("chennai",),
    "delhi": ("new delhi",),
    "new delhi": ("delhi",),
    # "Delhi NCR" is a two-word compound that essentially never appears
    # verbatim in a posting's location string — postings tag the specific
    # city instead ("New Delhi, India"). Maps to Delhi's own names only, not
    # to Gurgaon/Noida — those are separate, independently selectable
    # checkboxes on /preferences, and folding them in here would silently
    # reintroduce Gurgaon/Noida postings for someone who deliberately left
    # those unchecked.
    "delhi ncr": ("delhi", "new delhi"),
}


def _location_matches(job: RawJob, locations: list[str]) -> bool:
    location = job.location_raw.lower()
    if job.is_remote and any(loc.lower() == "remote" for loc in locations):
        return True
    for loc in locations:
        loc_lower = loc.lower()
        if loc_lower in location:
            return True
        if any(alias in location for alias in _CITY_ALIASES.get(loc_lower, ())):
            return True
    return False


def search_locations_for(filters: FiltersConfig, preference: JobPreference | None) -> list[str]:
    """Locations to feed LinkedIn/Indeed's own per-location search query
    (they scrape one location at a time, unlike the ATS/board sources that
    return everything and get narrowed down afterward). This must track the
    same preference this user actually set on /preferences — previously it
    read config.yaml's static filters.locations regardless of what the user
    picked, so e.g. adding "Bangalore" as a preferred location never
    actually searched LinkedIn/Indeed for Bangalore postings at all, no
    matter what showed up after filtering.
    """
    if preference is not None:
        if preference.location_mode == "remote_only":
            return ["remote"]
        if preference.location_mode == "specific_or_remote" and preference.preferred_locations:
            return preference.preferred_locations
    return filters.locations
