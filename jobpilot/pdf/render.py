import os
import platform
from pathlib import Path

if platform.system() == "Darwin":
    # WeasyPrint's native deps (Pango/cairo/gdk-pixbuf, installed via Homebrew)
    # aren't always on the dylib search path dyld uses for dlopen — set it
    # before the first `import weasyprint` so this works with no shell setup.
    homebrew_lib = "/opt/homebrew/lib" if Path("/opt/homebrew/lib").exists() else "/usr/local/lib"
    os.environ["DYLD_LIBRARY_PATH"] = homebrew_lib + os.pathsep + os.environ.get("DYLD_LIBRARY_PATH", "")

from jinja2 import Environment, FileSystemLoader  # noqa: E402
from weasyprint import HTML  # noqa: E402

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))


def _classify_link(link: str) -> tuple[str, str]:
    lower = link.lower()
    href = link if link.startswith(("http://", "https://")) else f"https://{link}"
    if "linkedin.com" in lower:
        return "LinkedIn", href
    if "github.com" in lower:
        return "GitHub", href
    return "Portfolio", href


def _build_contact_items(profile) -> list[dict]:
    """Short, clickable labels (Email, LinkedIn, GitHub, Portfolio) instead
    of raw URLs — same effect as an icon without needing to source/embed
    icon graphics, and it stays clean in both screen and print."""
    items = []
    if profile.location:
        items.append({"label": profile.location, "href": None})
    if profile.phone:
        items.append({"label": profile.phone, "href": None})
    if profile.email:
        items.append({"label": "Email", "href": f"mailto:{profile.email}"})
    for link in profile.links:
        label, href = _classify_link(link)
        items.append({"label": label, "href": href})
    return items


def render_resume_pdf(
    *,
    profile,
    summary: str,
    experience: list[dict],
    internships: list[dict],
    skills_emphasis: list[dict],
    projects: list[dict],
    education: list[dict],
    certifications: list[dict],
    output_path: Path,
) -> Path:
    # Internships render under the same "Experience" heading as regular
    # roles (tagged so the reader can still tell them apart) rather than a
    # separate section — reads as one continuous work history.
    combined_experience = [{**e, "is_internship": False} for e in experience] + [
        {**e, "is_internship": True} for e in internships
    ]

    css = (TEMPLATE_DIR / "resume.css").read_text()
    template = _env.get_template("resume.html.jinja")
    html_str = template.render(
        profile=profile,
        contact_items=_build_contact_items(profile),
        summary=summary,
        experience=combined_experience,
        skills_emphasis=skills_emphasis,
        projects=projects,
        education=education,
        certifications=certifications,
        css=css,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_str).write_pdf(str(output_path))
    return output_path
