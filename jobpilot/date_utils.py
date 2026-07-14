import difflib
from datetime import datetime

from dateutil import parser as dateutil_parser

_ONGOING_TERMS = ("present", "current", "ongoing", "now")
_MIN_DATE = datetime(1900, 1, 1)
_MAX_DATE = datetime(9999, 12, 31)


def _looks_ongoing(text: str) -> bool:
    """Free-text "end date" fields are hand-typed, so typos happen — the real
    profile data in this app has "Prresent" for one entry. A fixed regex
    tuned for one typo pattern (e.g. doubled "s") would miss others (this one
    doubles the "r" instead), so this compares against each ongoing term by
    similarity instead of trying to enumerate every possible misspelling.
    """
    word = text.strip().lower()
    if not word:
        return False
    return bool(difflib.get_close_matches(word, _ONGOING_TERMS, n=1, cutoff=0.75))


def parse_resume_date(text: str) -> datetime:
    """Best-effort parse of a free-text resume date fragment ("June 2025",
    "may 2022", "2019", "Prresent") into a sortable datetime. Ongoing/ present
    -like values sort as the latest possible date; unparseable text falls
    back to the earliest possible date rather than raising, since this drives
    display ordering, not anything that needs to fail loudly.
    """
    text = (text or "").strip()
    if not text:
        return _MIN_DATE
    if _looks_ongoing(text):
        return _MAX_DATE
    try:
        return dateutil_parser.parse(text, default=_MIN_DATE)
    except (ValueError, OverflowError):
        return _MIN_DATE


def resume_entry_sort_key(entry: dict) -> tuple[datetime, datetime]:
    """Sort key for a resume experience/internship entry dict carrying a
    combined "dates" string ("Jan 2024 - May 2025"). Sorts most-recent/
    ongoing-first when used with reverse=True; ties broken by start date so
    two ongoing roles order by when they began.
    """
    dates = entry.get("dates", "") or ""
    start_text, _, end_text = dates.partition(" - ")
    return (parse_resume_date(end_text), parse_resume_date(start_text))
