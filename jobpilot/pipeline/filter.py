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


def _location_matches(job: RawJob, locations: list[str]) -> bool:
    location = job.location_raw.lower()
    if job.is_remote and any(loc.lower() == "remote" for loc in locations):
        return True
    return any(loc.lower() in location for loc in locations)
