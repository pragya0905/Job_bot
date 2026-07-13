from pydantic import BaseModel, Field


class JobScoreOut(BaseModel):
    score: int = Field(ge=0, le=100)
    rationale: str = Field(max_length=400)
    matched_skills: list[str]
    missing_requirements: list[str]


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
