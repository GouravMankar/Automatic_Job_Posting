"""Prepare polished Instagram/WhatsApp-ready IT job posts.

The channel mode is intentionally independent of the personal resume pipeline:
it includes IT roles at every experience level and never uses the personal score.

The Instagram renderer is a deterministic Pillow template inspired by modern
corporate recruitment infographics: large hero area, source-derived job facts,
skill chips, job highlights, and a strong follow/comment CTA. It never invents
salary, batch, eligibility, or deadlines when the source does not provide them.
"""
from __future__ import annotations

import html
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .fetch import Job

DEFAULT_IT_TERMS = [
    "software", "developer", "engineer", "programmer", "qa", "quality assurance",
    "tester", "testing", "devops", "cloud", "aws", "azure", "gcp", "data analyst",
    "data engineer", "machine learning", "artificial intelligence", "cybersecurity",
    "security analyst", "soc", "network", "database", "technical support", "it support",
    "helpdesk", "frontend", "front-end", "backend", "back-end", "full stack", "fullstack",
    "ui/ux", "ux", "ui designer", "systems administrator", "site reliability", "sre",
    "mobile developer", "android", "ios", "automation", "scrum master", "technical writer",
]

SKILL_TERMS = [
    "Java", "Python", "JavaScript", "TypeScript", "C++", "C", "C#", ".NET", "SQL", "MySQL",
    "PostgreSQL", "MongoDB", "Oracle", "Spring Boot", "Spring MVC", "Spring", "Hibernate", "REST",
    "REST APIs", "GraphQL", "React", "Angular", "Vue", "Node.js", "Express", "Django", "Flask",
    "FastAPI", "Go", "Golang", "Rust", "Kotlin", "Swift", "Docker", "Kubernetes", "AWS", "Azure",
    "GCP", "Terraform", "Jenkins", "Git", "GitHub", "GitLab", "Linux", "Kafka", "Redis", "RabbitMQ",
    "Selenium", "Cypress", "Playwright", "JUnit", "Mockito", "PyTest", "HTML", "CSS", "Figma",
    "Power BI", "Tableau", "TensorFlow", "PyTorch", "Scikit-learn", "Cybersecurity", "Networking",
    "TCP/IP", "HTTP", "DNS", "Prometheus", "Grafana", "Salesforce", "SAP", "ServiceNow", "Jira",
    "Confluence", "CI/CD", "Microservices", "DevOps", "Machine Learning", "AI/ML", "Data Structures",
    "Algorithms", "System Design",
]

FONT_PATHS = [
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/Arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]
FONT_BOLD_PATHS = [
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("C:/Windows/Fonts/Arial Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def is_it_job(job: Job, terms: list[str] | None = None) -> bool:
    hay = f"{job.title} {job.description}".lower()
    return any(term.lower() in hay for term in (terms or DEFAULT_IT_TERMS))


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_")[:80] or "job"


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I | re.M)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" :-•")
    return None


def _find_font(bold: bool = False) -> str:
    choices = FONT_BOLD_PATHS if bold else FONT_PATHS
    for path in choices:
        if path.exists():
            return str(path)
    raise RuntimeError("No usable TrueType font found; install Arial or DejaVu Sans.")


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_find_font(bold), size=size)


def _bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    return draw.textbbox((0, 0), text, font=font)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    b = _bbox(draw, text, font)
    return b[2] - b[0]


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int | None = None) -> list[str]:
    words = str(text or "").split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        probe = f"{current} {word}"
        dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        if _text_width(dummy, probe, font) <= max_width:
            current = probe
        else:
            lines.append(current)
            current = word
    lines.append(current)

    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        # Keep the final line visible when a very long value remains.
        final = lines[-1]
        while _text_width(ImageDraw.Draw(Image.new("RGB", (1, 1))), final + "…", font) > max_width and len(final) > 8:
            final = final.rsplit(" ", 1)[0]
        lines[-1] = final + "…"
    return lines


def _fit_title(
    text: str,
    max_width: int,
    max_size: int = 64,
    min_size: int = 34,
    max_lines: int = 3,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for size in range(max_size, min_size - 1, -2):
        f = _font(size, True)
        lines = _wrap(text, f, max_width, max_lines=max_lines)
        if len(lines) <= max_lines and all(_text_width(dummy, line, f) <= max_width for line in lines):
            return f, lines
    f = _font(min_size, True)
    return f, _wrap(text, f, max_width, max_lines=max_lines)


def _clean(value: str | None, fallback: str = "Not specified", limit: int = 90) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return (value[: limit - 1] + "…") if len(value) > limit else (value or fallback)


def _extract_years_batch(text: str) -> str | None:
    return _first_match(text, [
        r"(?:batch|graduation year|pass(?:ing)? year|class of|graduating class)\s*[:\-]?\s*((?:20\d{2})(?:\s*[,/&-]\s*20\d{2})*)",
        r"((?:20\d{2})(?:\s*[,/&-]\s*20\d{2})*)\s*(?:batch|graduates?|graduation year)",
    ])


def _extract_eligibility(text: str) -> str | None:
    return _first_match(text, [
        r"(?:eligibility|educational qualification|education|academic qualification|qualification|degree)\s*[:\-]?\s*([^\n.;]{6,180})",
        r"(?:b\.?e\.?|b\.?tech|bca|mca|m\.?tech|mca|bsc|msc|bachelor(?:'s)?|master(?:'s)?)\s+(?:degree|in|or)\s+[^\n.;]{4,110}",
    ])


def _extract_experience(text: str) -> str | None:
    return _first_match(text, [
        r"(?:experience|exp(?:erience)?)\s*[:\-]?\s*(\d+\s*(?:[-–to]+)\s*\d+\s*years?|\d+\+?\s*years?|fresher|entry[- ]level|intern(?:ship)?)",
        r"(fresher|entry[- ]level|intern(?:ship)?|\d+\s*(?:[-–to]+)\s*\d+\s*years?|\d+\+?\s*years?)\s*(?:of experience)?",
        r"(?:minimum|at least)\s+(\d+\+?\s*years?)",
    ])


def _extract_salary(job: Job, text: str) -> str | None:
    if getattr(job, "salary", None):
        return re.sub(r"\s+", " ", str(job.salary)).strip()
    return _first_match(text, [
        r"(?:salary|compensation|pay|ctc|package|pay range|base salary|annual salary)\s*[:\-]?\s*([^\n.;]{2,120})",
        r"(₹\s?[\d,.]+\s*(?:LPA|lakhs?|per annum)?(?:\s*[-–]\s*₹?\s?[\d,.]+\s*(?:LPA|lakhs?)?)?)",
        r"(\$\s?[\d,.]+\s*(?:k|K)?\s*(?:[-–]\s*\$?\s?[\d,.]+\s*(?:k|K)?)?)",
    ])


def _extract_deadline(text: str) -> str | None:
    return _first_match(text, [
        r"(?:last date|deadline|apply by|closing date|application deadline|applications close)\s*[:\-]?\s*([^\n.;]{3,80})",
    ])


def _extract_employment(text: str) -> str | None:
    return _first_match(text, [
        r"(?:employment type|job type|work type|commitment)\s*[:\-]?\s*(full[- ]time|part[- ]time|contract|internship|temporary|permanent|freelance)",
        r"\b(full[- ]time|part[- ]time|contract|internship|temporary|permanent|freelance)\b",
    ])


def _extract_skills(text: str) -> list[str]:
    lower = text.lower()
    hits: list[str] = []
    for skill in SKILL_TERMS:
        if skill.lower() in lower and skill not in hits:
            hits.append(skill)
    return hits[:12]


def _extract_highlights(text: str) -> list[str]:
    highlights: list[str] = []
    for raw in re.split(r"\n|•|\u2022", text):
        line = re.sub(r"^\s*[-*•▪◦]+\s*", "", raw).strip()
        if not 28 <= len(line) <= 170:
            continue
        low = line.lower()
        if any(k in low for k in (
            "responsib", "work", "build", "develop", "design", "manage", "collaborat",
            "support", "lead", "create", "test", "own", "deliver", "maintain", "scale",
        )):
            highlights.append(line)
        if len(highlights) >= 4:
            break
    if not highlights:
        highlights = [
            "See the official job description for responsibilities and team details.",
            "Review the official posting for role-specific requirements and benefits.",
        ]
    return highlights[:4]


def extract_details(job: Job) -> dict:
    text = job.description or ""
    skills = _extract_skills(text)
    return {
        "experience": _extract_experience(text) or "Not specified",
        "batch": _extract_years_batch(text) or "Not specified",
        "eligibility": _extract_eligibility(text) or "Not specified",
        "salary": _extract_salary(job, text) or "Not specified",
        "deadline": _extract_deadline(text) or "Not specified",
        "employment_type": _extract_employment(text) or "Not specified",
        "skills": skills or ["See official job description"],
        "highlights": _extract_highlights(text),
    }


def make_caption(job: Job, hashtags: list[str] | None = None) -> str:
    details = extract_details(job)
    tags = hashtags or ["#ITJobs", "#Hiring", "#Jobs", "#Career", "#TechJobs"]
    skills = ", ".join(details["skills"])
    return (
        f"🚨 HIRING ALERT\n\n"
        f"🏢 Company: {job.company}\n"
        f"💼 Role: {job.title}\n"
        f"📍 Location: {job.location or 'Not specified'}\n"
        f"🎓 Experience: {details['experience']}\n"
        f"🎓 Batch / Eligibility: {details['batch']} | {details['eligibility']}\n"
        f"💰 Salary: {details['salary']}\n"
        f"🛠 Required skills: {skills}\n"
        f"🗓 Deadline: {details['deadline']}\n"
        f"💼 Employment: {details['employment_type']}\n\n"
        f"🔗 Follow this page and comment LINK to request the application URL.\n\n"
        f"Please verify eligibility and all details on the official application page.\n\n"
        f"{' '.join(tags)}"
    )


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

NAVY = "#051A38"
NAVY_2 = "#082A59"
BLUE = "#167CF2"
CYAN = "#18B7F7"
WHITE = "#FFFFFF"
LIGHT = "#F3F8FF"
TEXT_BLUE = "#12356C"
MUTED = "#4E6E98"
YELLOW = "#FFD019"
BORDER = "#187CEB"


def _rounded_panel(draw: ImageDraw.ImageDraw, box, fill, outline=None, radius=28, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width if outline else 1)


def _shadowed_panel(canvas: Image.Image, box, fill, outline=None, radius=28, shadow=(0, 8, 22, 55)):
    x1, y1, x2, y2 = box
    shadow_img = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_img)
    ox, oy, blur, alpha = shadow
    sd.rounded_rectangle((x1 + ox // 2, y1 + oy, x2 + ox // 2, y2 + oy), radius=radius, fill=(0, 0, 0, alpha))
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(shadow_img)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2 if outline else 1)


def _draw_text(draw, xy, text, size, fill, bold=False, anchor=None):
    draw.text(xy, text, font=_font(size, bold), fill=fill, anchor=anchor)


def _draw_wrapped(draw, xy, text, size, max_width, fill, bold=False, spacing=5, max_lines=None) -> int:
    f = _font(size, bold)
    lines = _wrap(text, f, max_width, max_lines=max_lines)
    x, y = xy
    b = draw.textbbox((0, 0), "Ag", font=f)
    line_h = b[3] - b[1]
    for idx, line in enumerate(lines):
        draw.text((x, y + idx * (line_h + spacing)), line, font=f, fill=fill)
    return len(lines) * (line_h + spacing) - spacing


def _draw_icon(draw, kind: str, center: tuple[int, int], fill: str, scale: int = 28):
    """Small vector icons so the banner does not depend on emoji fonts."""
    cx, cy = center
    s = scale
    draw.ellipse((cx - s, cy - s, cx + s, cy + s), fill=fill)
    ink = WHITE
    if kind == "company":
        draw.rectangle((cx - 9, cy - 11, cx + 8, cy + 13), fill=ink)
        for yy in (-6, 0, 6):
            for xx in (-5, 2):
                draw.rectangle((cx + xx, cy + yy, cx + xx + 3, cy + yy + 3), fill=fill)
    elif kind == "location":
        draw.ellipse((cx - 10, cy - 13, cx + 10, cy + 9), outline=ink, width=4)
        draw.ellipse((cx - 3, cy - 6, cx + 3, cy), fill=ink)
        draw.polygon([(cx - 10, cy + 2), (cx, cy + 15), (cx + 10, cy + 2)], fill=ink)
    elif kind == "experience":
        draw.rounded_rectangle((cx - 12, cy - 7, cx + 12, cy + 12), radius=4, outline=ink, width=3)
        draw.rounded_rectangle((cx - 6, cy - 13, cx + 6, cy - 5), radius=3, outline=ink, width=3)
    elif kind == "batch":
        draw.polygon([(cx - 14, cy - 5), (cx, cy - 13), (cx + 14, cy - 5), (cx, cy + 3)], fill=ink)
        draw.rectangle((cx - 8, cy + 3, cx + 8, cy + 7), fill=ink)
        draw.line((cx + 12, cy - 5, cx + 12, cy + 9), fill=ink, width=3)
    elif kind == "salary":
        draw.rounded_rectangle((cx - 10, cy - 14, cx + 10, cy + 14), radius=6, fill=ink)
        _draw_text(draw, (cx, cy), "₹", 18, fill, True, anchor="mm")
    elif kind == "employment":
        draw.rounded_rectangle((cx - 12, cy - 11, cx + 12, cy + 11), radius=5, outline=ink, width=3)
        draw.line((cx, cy - 8, cx, cy + 8), fill=ink, width=3)
        draw.line((cx - 7, cy - 3, cx + 7, cy - 3), fill=ink, width=3)
    elif kind in {"date", "deadline"}:
        draw.rounded_rectangle((cx - 11, cy - 10, cx + 11, cy + 11), radius=4, outline=ink, width=3)
        draw.line((cx - 11, cy - 3, cx + 11, cy - 3), fill=ink, width=3)
        draw.line((cx - 6, cy - 14, cx - 6, cy - 7), fill=ink, width=3)
        draw.line((cx + 6, cy - 14, cx + 6, cy - 7), fill=ink, width=3)
    elif kind == "skills":
        for ang in range(0, 360, 60):
            rad = math.radians(ang)
            x = cx + int(12 * math.cos(rad))
            y = cy + int(12 * math.sin(rad))
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=ink)
        draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), outline=ink, width=3)
    elif kind == "highlights":
        draw.rounded_rectangle((cx - 10, cy - 14, cx + 10, cy + 14), radius=4, outline=ink, width=3)
        draw.line((cx - 5, cy - 4, cx + 6, cy - 4), fill=ink, width=3)
        draw.line((cx - 5, cy + 3, cx + 6, cy + 3), fill=ink, width=3)
    elif kind == "cta":
        draw.ellipse((cx - 8, cy - 12, cx + 8, cy + 4), fill=ink)
        draw.rounded_rectangle((cx - 14, cy + 5, cx + 14, cy + 14), radius=5, fill=ink)


def _gradient_background(size: tuple[int, int], left=(5, 26, 56), right=(14, 106, 194)) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for x in range(w):
        t = x / max(w - 1, 1)
        # subtle ease curve
        tt = t * t * (3 - 2 * t)
        c = tuple(int(left[i] * (1 - tt) + right[i] * tt) for i in range(3))
        for y in range(h):
            # slightly darker toward bottom
            shade = 1 - 0.10 * (y / h)
            px[x, y] = tuple(max(0, min(255, int(v * shade))) for v in c)
    return img


def _hero_glow(canvas: Image.Image, box: tuple[int, int, int, int]):
    x1, y1, x2, y2 = box
    glow = Image.new("RGBA", (x2 - x1, y2 - y1), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r, alpha in [(300, 18), (240, 25), (180, 32)]:
        gd.ellipse((300-r, 220-r, 300+r, 220+r), fill=(50, 170, 255, alpha))
    # Abstract glass building.
    bx1, by1, bx2, by2 = 180, 52, 515, 360
    gd.polygon([(bx1, by2), (bx1 + 65, by1), (bx2, by1 + 28), (bx2, by2)], fill=(20, 71, 123, 185), outline=(97, 177, 255, 200))
    for col in range(7):
        xx = bx1 + 34 + col * 46
        gd.line((xx, by1 + 10, xx - 6, by2), fill=(114, 191, 255, 90), width=2)
    for row in range(6):
        yy = by1 + 45 + row * 48
        gd.line((bx1 + 12, yy, bx2 - 10, yy + 10), fill=(124, 197, 255, 72), width=2)
    glow = glow.filter(ImageFilter.GaussianBlur(0.5))
    canvas.alpha_composite(glow, dest=(x1, y1))


def _load_company_image(assets_dir: Path, company: str, hero: bool = False) -> Image.Image | None:
    slug = _safe_name(company.lower())
    suffixes = ("_hero", "_banner") if hero else ("",)
    exts = ("png", "jpg", "jpeg", "webp")
    candidates: list[Path] = []
    for suffix in suffixes:
        for ext in exts:
            candidates.append(assets_dir / f"{slug}{suffix}.{ext}")
    for path in candidates:
        if path.exists():
            try:
                return Image.open(path).convert("RGB")
            except Exception:
                pass
    return None


def _place_cover(canvas: Image.Image, src: Image.Image, box: tuple[int, int, int, int], radius: int = 0, opacity: int = 255):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    fitted = ImageOps.fit(src, (w, h), method=Image.Resampling.LANCZOS)
    if opacity < 255:
        alpha = fitted.convert("L").point(lambda p: int(p * opacity / 255))
        fitted = fitted.convert("RGBA")
        fitted.putalpha(alpha)
    else:
        fitted = fitted.convert("RGBA")
    if radius:
        mask = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
        fitted.putalpha(mask)
    canvas.alpha_composite(fitted, dest=(x1, y1))


def _format_posted_date(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "Not specified"
    raw2 = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw2)
        return dt.strftime("%d %b %Y")
    except ValueError:
        m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", raw)
        if m:
            return f"{m.group(3).zfill(2)} {datetime.strptime(m.group(1)+m.group(2)+m.group(3), '%Y%m%d').strftime('%b %Y')}"
        return _clean(raw, limit=18)


def _field_card(draw, x: int, y: int, w: int, label: str, value: str, kind: str, color: str):
    _draw_icon(draw, kind, (x + 28, y + 28), color, 28)
    _draw_text(draw, (x + 68, y + 4), label, 16, "#3D67A0")
    vf = _font(20 if len(value) <= 18 else 17, True)
    lines = _wrap(value, vf, w - 72, max_lines=2)
    for i, line in enumerate(lines):
        draw.text((x + 68, y + 28 + i * 23), line, font=vf, fill=TEXT_BLUE)


def make_instagram_png_banner(job: Job, output: Path, assets_dir: str | Path = "jobhunt/channel_assets/companies") -> Path:
    """Create a 1080x1350 Instagram poster matching the reference layout.

    The template is deterministic and uses only source-derived job data.
    Optional assets:
      <company-slug>_hero.(png|jpg|jpeg|webp)  -> hero/building image
      <company-slug>.(png|jpg|jpeg|webp)       -> company logo/brand image
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    assets = Path(assets_dir)
    W, H = 1080, 1350

    img = _gradient_background((W, H)).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # Hero section.
    draw.rectangle((0, 0, W, 418), fill=(6, 28, 59, 255))
    _hero_glow(img, (520, 0, W, 418))

    hero = _load_company_image(assets, job.company, hero=True)
    if hero:
        _place_cover(img, hero, (560, 18, 1080, 395), radius=0, opacity=220)
        overlay = Image.new("RGBA", (520, 377), (4, 30, 63, 0))
        od = ImageDraw.Draw(overlay)
        od.rectangle((0, 0, 520, 377), fill=(4, 30, 63, 80))
        img.alpha_composite(overlay, dest=(560, 18))

    # Company mark + name.
    logo = _load_company_image(assets, job.company, hero=False)
    if logo:
        _place_cover(img, logo, (46, 35, 124, 113), radius=14)
    else:
        draw.ellipse((50, 38, 124, 112), fill="#1385EC")
        draw.ellipse((66, 54, 108, 96), outline="#061A36", width=10)
        draw.arc((58, 46, 116, 104), 300, 120, fill="#0EE0FF", width=7)
    _draw_text(draw, (142, 42), _clean(job.company, "Company", 28), 43, WHITE, True)
    _draw_text(draw, (144, 91), "HIRING • CAREERS • TECHNOLOGY", 16, "#C9E2FF")

    # Hiring alert pill.
    _rounded_panel(draw, (46, 145, 485, 211), YELLOW, radius=32)
    # Speaker icon.
    draw.polygon([(72, 166), (86, 166), (101, 153), (101, 201), (86, 188), (72, 188)], fill="#0A2449")
    draw.arc((93, 157, 123, 196), 300, 60, fill="#0A2449", width=3)
    _draw_text(draw, (146, 157), "HIRING ALERT", 31, "#09234A", True)

    # Right-side brand cue.
    if hero is None:
        _draw_text(draw, (935, 54), "YOUR\nNEXT\nCAREER\nMOVE", 23, WHITE, True, anchor="ma")
    else:
        _draw_text(draw, (975, 50), "BUILD\nWHAT'S\nNEXT", 23, WHITE, True, anchor="ma")

    # Role title with wrapping.
    title_font, title_lines = _fit_title(job.title, 540, max_size=54, min_size=32, max_lines=2)
    title_y = 232
    title_bbox = draw.textbbox((0, 0), "Ag", font=title_font)
    title_h = title_bbox[3] - title_bbox[1]
    for i, line in enumerate(title_lines):
        draw.text((46, title_y + i * (title_h + 2)), line, font=title_font, fill=WHITE)

    # Short source-safe subtitle.
    after_title = title_y + len(title_lines) * (title_h + 2)
    subtitle = f"Explore the {job.company} opportunity and review the official posting for complete details."
    _draw_wrapped(draw, (50, min(after_title + 8, 347)), subtitle, 17, 540, "#EAF4FF", spacing=3, max_lines=2)

    # Details card. Keep a fixed hero-to-card gap so long titles never collide.
    details = extract_details(job)
    _shadowed_panel(img, (38, 408, 1042, 719), LIGHT, outline="#D7E9FF", radius=30, shadow=(0, 7, 14, 35))
    draw = ImageDraw.Draw(img)

    cols = [58, 300, 542, 784]
    rows = [439, 574]
    fw = 215
    fields = [
        (0, 0, "COMPANY", _clean(job.company, limit=28), "company", "#1B85EF"),
        (1, 0, "LOCATION", _clean(job.location, limit=30), "location", "#5346E8"),
        (2, 0, "EXPERIENCE", _clean(details["experience"], limit=28), "experience", "#1EA264"),
        (3, 0, "BATCH / ELIGIBILITY", _clean(details["batch"], limit=24), "batch", "#FFA516"),
        (0, 1, "SALARY", _clean(details["salary"], limit=29), "salary", "#EE4B73"),
        (1, 1, "EMPLOYMENT TYPE", _clean(details["employment_type"], limit=23), "employment", "#18A9CD"),
        (2, 1, "JOB POSTED", _format_posted_date(job.posted_at), "date", "#694AE8"),
        (3, 1, "LAST DATE", _clean(details["deadline"], limit=22), "deadline", "#E94C78"),
    ]
    for ci, ri, label, value, kind, color in fields:
        _field_card(draw, cols[ci], rows[ri], fw, label, value, kind, color)

    # Eligibility note line inside the details card.
    eligibility = _clean(details["eligibility"], limit=115)
    if eligibility != "Not specified":
        _draw_wrapped(draw, (60, 688), f"Eligibility: {eligibility}", 14, 940, "#3B6090", spacing=2, max_lines=1)

    # Skills panel + highlights panel.
    _shadowed_panel(img, (38, 728, 652, 1008), NAVY_2, outline="#1478DB", radius=28, shadow=(0, 6, 12, 30))
    _shadowed_panel(img, (670, 728, 1042, 1008), NAVY_2, outline="#1478DB", radius=28, shadow=(0, 6, 12, 30))
    draw = ImageDraw.Draw(img)

    _draw_icon(draw, "skills", (95, 774), "#3159E8", 28)
    _draw_text(draw, (145, 751), "Required Skills", 28, WHITE, True)
    _draw_text(draw, (145, 789), "Based on the job description", 14, "#BBD4F5")

    sx, sy = 68, 827
    max_x = 622
    skill_font = _font(15, False)
    for skill in details["skills"]:
        chip_text = _clean(skill, limit=26)
        tw = _text_width(draw, chip_text, skill_font)
        w = tw + 31
        if sx + w > max_x:
            sx = 68
            sy += 43
        if sy + 34 > 978:
            break
        _rounded_panel(draw, (sx, sy, sx + w, sy + 34), "#123F79", outline="#278DF0", radius=17)
        _draw_text(draw, (sx + 15, sy + 7), chip_text, 15, "#EFF7FF")
        sx += w + 8

    _draw_icon(draw, "highlights", (715, 774), "#6A49E7", 28)
    _draw_text(draw, (765, 751), "Job Highlights", 28, WHITE, True)
    yy = 823
    for idx, highlight in enumerate(details["highlights"][:3]):
        accent = ["#1E83F5", "#16BC8D", "#FFA815"][idx % 3]
        _draw_icon(draw, "cta", (708, yy + 15), accent, 14)
        h = _draw_wrapped(draw, (739, yy), _clean(highlight, limit=88), 14, 280, "#EAF4FF", spacing=2, max_lines=2)
        yy += max(57, h + 10)

    # CTA banner.
    draw.rounded_rectangle((38, 1024, 1042, 1176), radius=30, fill=YELLOW)
    _draw_icon(draw, "cta", (94, 1100), "#092B57", 29)
    _draw_text(draw, (140, 1051), "FOLLOW + COMMENT", 20, "#09234A", True)
    _rounded_panel(draw, (420, 1048, 565, 1105), "#092B57", radius=25)
    _draw_text(draw, (492, 1057), "'LINK'", 21, WHITE, True, anchor="ma")
    _draw_text(draw, (140, 1091), "FOR APPLY URL", 20, "#09234A", True)

    # Right CTA panel.
    draw.polygon([(693, 1024), (1042, 1024), (1042, 1176), (646, 1176)], fill="#167AF1")
    draw.ellipse((742, 1072, 812, 1142), fill="#FFFFFF")
    _draw_text(draw, (777, 1107), "IG", 17, "#D32DE8", True, anchor="mm")
    _draw_text(draw, (835, 1057), "Follow for more", 20, WHITE, True)
    _draw_text(draw, (835, 1092), "IT job updates!", 20, WHITE, True)

    # Footer.
    draw.line((42, 1258, 332, 1258), fill="#4B76A9", width=2)
    draw.line((748, 1258, 1038, 1258), fill="#4B76A9", width=2)
    _draw_text(draw, (540, 1234), "✦  Good Opportunities. Better Careers.  ✦", 17, "#D8E8FF", anchor="ma")

    # Soft outer vignette.
    vignette = Image.new("L", (W, H), 0)
    vp = vignette.load()
    for y in range(H):
        for x in range(W):
            dx = abs(x - W / 2) / (W / 2)
            dy = abs(y - H / 2) / (H / 2)
            edge = max(dx, dy)
            vp[x, y] = max(0, int((edge - 0.55) * 120))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    overlay.putalpha(vignette)
    img = Image.alpha_composite(img, overlay)

    img.convert("RGB").save(output, format="PNG", optimize=True)
    return output


def make_svg_banner(job: Job, output: Path) -> Path:
    """Backward-compatible SVG fallback; PNG is the preferred Instagram asset."""
    output.parent.mkdir(parents=True, exist_ok=True)
    details = extract_details(job)
    title = html.escape(_clean(job.title, "Job opportunity", 70))
    company = html.escape(_clean(job.company, "Company", 45))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1350" viewBox="0 0 1080 1350">
<defs><linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="#061A36"/><stop offset="1" stop-color="#0E6AC2"/></linearGradient></defs>
<rect width="1080" height="1350" fill="url(#g)"/>
<rect x="38" y="397" width="1004" height="311" rx="30" fill="#F3F8FF"/>
<text x="46" y="174" font-family="Arial,sans-serif" font-size="31" font-weight="700" fill="#09234A">HIRING ALERT</text>
<text x="46" y="285" font-family="Arial,sans-serif" font-size="54" font-weight="700" fill="#FFFFFF">{title}</text>
<text x="60" y="470" font-family="Arial,sans-serif" font-size="22" fill="#12356C">Company: {company}</text>
<text x="60" y="520" font-family="Arial,sans-serif" font-size="22" fill="#12356C">Location: {html.escape(_clean(job.location))}</text>
<text x="60" y="570" font-family="Arial,sans-serif" font-size="22" fill="#12356C">Experience: {html.escape(details['experience'])}</text>
<text x="60" y="620" font-family="Arial,sans-serif" font-size="22" fill="#12356C">Salary: {html.escape(details['salary'])}</text>
<rect x="38" y="1024" width="1004" height="152" rx="30" fill="#FFD019"/>
<text x="100" y="1114" font-family="Arial,sans-serif" font-size="27" font-weight="700" fill="#09234A">FOLLOW + COMMENT 'LINK' FOR APPLY URL</text>
</svg>'''
    output.write_text(svg, encoding="utf-8")
    return output


def prepare_posts(jobs: Iterable[Job], out_dir: str | Path = "out/channel", hashtags=None) -> list[dict]:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    posts = []
    for job in jobs:
        slug = _safe_name(f"{job.company}_{job.title}_{job.job_id}")
        banner = make_instagram_png_banner(job, root / f"{slug}.png")
        svg_banner = make_svg_banner(job, root / f"{slug}.svg")
        details = extract_details(job)
        caption = make_caption(job, hashtags)
        posts.append({
            "job_id": job.job_id,
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "url": job.url,
            "banner": str(banner),
            "svg_fallback": str(svg_banner),
            "caption": caption,
            "details": details,
            "comment_keyword": "LINK",
            "cta": "Follow + comment LINK for the application URL",
            "status": "READY_FOR_REVIEW",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    manifest = root / "posts.json"
    manifest.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")
    return posts
