SENTENCE_END_CHARS = (".", "!", "?", ":")


def split_bullet_lines(text: str) -> list[str]:
    """Split a textarea's "one bullet per line" content into bullets.

    Pasted resume text often has soft line-wraps mid-sentence (copied from a
    PDF/Word doc where a single bullet visually wraps across lines). Treating
    every newline as a bullet boundary breaks those into fragments — e.g.
    "...resulting in $5.5" / "million annual revenue..." as two bullets
    instead of one. A line that doesn't end in sentence-ending punctuation is
    almost always a wrapped continuation, not a new bullet, so it gets
    merged into the previous line instead.
    """
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    merged: list[str] = []
    for line in raw_lines:
        if merged and not merged[-1].endswith(SENTENCE_END_CHARS):
            merged[-1] = f"{merged[-1]} {line}"
        else:
            merged.append(line)
    return merged


def split_commas(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def clean_location_entries(text: str, existing: list[str] | None = None) -> list[str]:
    """Parse the Preferences page's free-text "other locations" field into a
    deduped list of plausible city names.

    Real city names vary too much (compound names, abbreviations like "NCR")
    to validate against a fixed pattern, so this only rejects clear junk —
    single characters, pure numbers, entries with no letters at all — and
    dedupes case-insensitively (including against the curated location list
    already selected) rather than enforcing a strict format.
    """
    seen = {loc.lower() for loc in (existing or [])}
    cleaned: list[str] = []
    for raw in split_commas(text):
        candidate = " ".join(raw.split())  # collapse internal whitespace
        if len(candidate) < 2:
            continue
        if not any(ch.isalpha() for ch in candidate):
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(candidate)
    return cleaned
