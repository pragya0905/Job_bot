from pydantic import BaseModel, Field


class JobScoreOut(BaseModel):
    score: int = Field(ge=0, le=100)
    # Deliberately REQUIRED (not Optional) and placed before the long
    # free-text `rationale` field. Both choices were forced by testing
    # against the real model, not stylistic: as `str | None`, gemma3:4b
    # silently omitted the key entirely (no error, just absent — Pydantic's
    # default quietly filled in None) roughly as often as it populated it.
    # Made required, the model reliably attempts it every time — the literal
    # sentinel string "none" (checked in score.py's clean_stated_salary)
    # is how "not stated" gets communicated instead of Python-level null.
    # Placing it before `rationale` also fixed a separate failure mode:
    # after it, the model would sometimes leave the JSON string unterminated
    # (missing closing quote) partway through the rationale, cutting off
    # the whole object before this field was ever reached.
    stated_salary: str
    rationale: str = Field(max_length=400)
    matched_skills: list[str]
    missing_requirements: list[str]


class CompClassificationOut(BaseModel):
    """Used only to classify a job into a bucket in the static
    comp_reference table (pipeline/comp_reference.py) — the model never
    generates a compensation number itself, only picks which pre-researched
    bucket a posting falls into. Kept as its own tiny schema (separate LLM
    call) rather than folded into JobScoreOut: JobScoreOut is already
    sensitive to field count/ordering (see stated_salary's comment above),
    and this only needs to run for the minority of jobs where stated_salary
    came back empty, so a shared call would waste a classification attempt
    on every job that already has a real stated figure.
    """

    role_family: str
    seniority_level: str
    location_bucket: str


class GeneratedBulletsOut(BaseModel):
    """A separate, dedicated call (own schema, own prompt) rather than folded
    into TailoredResumeOut — keeps the existing, already-tested main
    tailoring call untouched, and only runs at all for entries that opted
    into raw-description mode (pipeline/tailor.py's
    _generate_bullets_from_description). No maxLength/minItems constraints
    on `bullets`, per the established pattern of enforcing counts/lengths in
    Python rather than risking the grammar-compiler failures those
    constraints have caused elsewhere in this schema set.
    """

    bullets: list[str]


class TailoredExperience(BaseModel):
    company: str
    title: str
    location: str
    dates: str
    bullets: list[str]


class SkillCategoryOut(BaseModel):
    category: str
    skills: list[str]


class TailoredResumeOut(BaseModel):
    summary: str
    experience: list[TailoredExperience]
    internships: list[TailoredExperience] = Field(default_factory=list)
    skills_emphasis: list[SkillCategoryOut]
    # No max_length here — a maxLength constraint on this field breaks
    # Ollama's grammar compiler for this schema ("failed to parse grammar",
    # confirmed by isolating it: the field alone is fine, the length cap on
    # it is what fails). Length is enforced in Python instead, after the
    # response comes back — see tailor.py's COVER_LETTER_MAX_LENGTH.
    cover_letter: str
