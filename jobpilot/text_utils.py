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
