#!/usr/bin/env python3
"""Extract and analyze a resume PDF without sending it to an external service.

Usage:
    python3 resume_job_analyzer.py ~/Downloads/resume.pdf
    python3 resume_job_analyzer.py resume.pdf --json --output analysis.json

Dependencies:
    python3 -m pip install pdfplumber pypdf
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
DATE = rf"(?:{MONTH}\s+)?\d{{4}}|Present|Current"
DATE_RANGE_RE = re.compile(rf"(?P<start>{DATE})\s*[-–—]\s*(?P<end>{DATE})", re.I)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]*)?(?:\(?\d{3}\)?[\s.-]*)\d{3}[\s.-]*\d{4}(?!\d)")
URL_RE = re.compile(r"(?:(?:https?://)?(?:www\.)?(?:linkedin\.com|github\.com|[A-Z0-9.-]+\.[A-Z]{2,})(?:/[^\s,;•]*)?)", re.I)
LOCATION_RE = re.compile(r"\b([A-Z][A-Za-z .'-]+,\s*[A-Z]{2})(?:\b|$)")
FULL_DATE_RE = re.compile(rf"^(?:{MONTH}\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|{MONTH}\s+\d{{4}})$", re.I)
NAME_TOKEN_RE = re.compile(r"^[A-Z][A-Za-z'’.\-]*$")

# Letter-spaced display type ("S T E F F A N E E") only collapses back into words at a
# wider tolerance; 4pt reassembles it without gluing adjacent words in body copy.
X_TOLERANCE = 4
Y_TOLERANCE = 3
MIN_GUTTER_POINTS = 18


SECTION_NAMES = {
    "summary": "summary",
    "profile": "summary",
    "objective": "summary",
    "education": "education",
    "technical skills": "skills",
    "skills": "skills",
    "work experience": "experience",
    "experience": "experience",
    "professional experience": "experience",
    "employment": "experience",
    "projects": "projects",
    "certifications": "certifications",
    "licenses": "certifications",
    "awards": "awards",
    "publications": "publications",
    "volunteer experience": "volunteer",
    "volunteer": "volunteer",
}


TECHNOLOGY_SKILLS = OrderedDict(
    [
        (
            "Languages",
            [
                "TypeScript",
                "JavaScript",
                "Python",
                "Go",
                "Java",
                "C#",
                "C++",
                "Rust",
                "Ruby",
                "PHP",
                "Perl",
                "Bash",
                "SQL",
            ],
        ),
        (
            "Frontend & Web",
            [
                "React",
                "Next.js",
                "Angular",
                "Vue",
                "Svelte",
                "Node.js",
                "GraphQL",
                "REST",
                "micro-frontends",
                "module federation",
                "Tailwind CSS",
                "SCSS",
                "design systems",
                "accessibility",
                "WCAG",
            ],
        ),
        (
            "Testing & Quality",
            [
                "Playwright",
                "Vitest",
                "Jest",
                "Cypress",
                "Selenium",
                "React Testing Library",
                "axe-core",
                "test automation",
                "quality engineering",
            ],
        ),
        (
            "Cloud, Platform & Infrastructure",
            [
                "AWS",
                "Aurora",
                "RDS",
                "DynamoDB",
                "S3",
                "Lambda",
                "SQS",
                "Kubernetes",
                "Istio",
                "Argo CD",
                "Terraform",
                "Terragrunt",
                "Vault",
                "Docker",
                "Vercel",
                "CloudFront",
                "DNS",
                "OAuth",
                "IAM",
            ],
        ),
        (
            "Build, CI/CD & Observability",
            [
                "pnpm",
                "Turborepo",
                "RSBuild",
                "webpack",
                "Bazel",
                "ESLint",
                "SonarQube",
                "GitHub Actions",
                "GitLab CI",
                "CI/CD",
                "APM",
                "Core Web Vitals",
                "Dependabot",
                "SBOM",
            ],
        ),
        (
            "Security",
            [
                "application security",
                "product security",
                "cybersecurity",
                "SAML",
                "Duo",
                "single sign-on",
                "multi-factor authentication",
                "RBAC",
                "role-based access control",
                "CORS",
                "MITRE ATT&CK",
                "zero trust",
                "security orchestration",
                "SOAR",
            ],
        ),
        (
            "Delivery & Collaboration",
            [
                "technical leadership",
                "stakeholder management",
                "cross-functional",
                "design review",
                "code review",
                "technical documentation",
                "mentoring",
                "release management",
                "program management",
            ],
        ),
    ]
)


TECHNOLOGY_JOB_FAMILIES = OrderedDict(
    [
        (
            "Senior/Staff Software Engineering",
            {
                "terms": {
                    "software engineer": 8,
                    "senior software engineer": 10,
                    "full stack": 6,
                    "backend": 4,
                    "frontend": 4,
                    "typescript": 3,
                    "javascript": 3,
                    "python": 2,
                    "go": 2,
                    "react": 3,
                    "graphql": 2,
                    "api": 2,
                    "microservice": 2,
                    "software architecture": 4,
                },
                "description": "Senior individual-contributor roles building and evolving production software systems.",
            },
        ),
        (
            "Frontend / Full-stack Engineering",
            {
                "terms": {
                    "frontend": 7,
                    "react": 5,
                    "next.js": 4,
                    "micro-frontends": 6,
                    "module federation": 5,
                    "design systems": 4,
                    "accessibility": 3,
                    "wcag": 3,
                    "graphql": 2,
                    "typescript": 3,
                    "javascript": 3,
                    "ui": 2,
                },
                "description": "Frontend platform, design-system, or full-stack product engineering roles.",
            },
        ),
        (
            "Cloud / Platform / DevOps Engineering",
            {
                "terms": {
                    "platform": 6,
                    "cloud": 4,
                    "aws": 4,
                    "kubernetes": 6,
                    "terraform": 5,
                    "istio": 4,
                    "argo": 3,
                    "docker": 3,
                    "vault": 3,
                    "ci/cd": 4,
                    "deployment": 3,
                    "infrastructure": 4,
                    "observability": 3,
                    "sre": 5,
                },
                "description": "Cloud infrastructure, platform reliability, developer platform, or DevOps roles.",
            },
        ),
        (
            "Application / Product Security Engineering",
            {
                "terms": {
                    "security": 5,
                    "application security": 8,
                    "product security": 8,
                    "cybersecurity": 6,
                    "soar": 7,
                    "saml": 3,
                    "oauth": 3,
                    "rbac": 4,
                    "role-based access control": 4,
                    "cors": 3,
                    "mitre att&ck": 5,
                    "zero trust": 5,
                    "vulnerability": 3,
                },
                "description": "Security-minded engineering roles focused on product, application, identity, or cloud security.",
            },
        ),
        (
            "Engineering Productivity / Quality Automation",
            {
                "terms": {
                    "test automation": 7,
                    "playwright": 5,
                    "cypress": 4,
                    "selenium": 4,
                    "vitest": 3,
                    "jest": 3,
                    "ci trace": 3,
                    "ci/cd": 3,
                    "developer productivity": 6,
                    "engineering maturity": 5,
                    "monorepo": 4,
                    "build tooling": 4,
                    "quality": 2,
                },
                "description": "Developer-experience, test infrastructure, build tooling, and engineering-quality roles.",
            },
        ),
        (
            "Technical Lead / Engineering Delivery",
            {
                "terms": {
                    "technical leadership": 6,
                    "stakeholder": 4,
                    "cross-functional": 4,
                    "coordinat": 3,
                    "delivery": 3,
                    "roadmap": 3,
                    "design review": 4,
                    "code review": 3,
                    "mentoring": 3,
                    "without direct authority": 6,
                    "program management": 4,
                    "release": 2,
                },
                "description": "Technical lead, staff engineer, or engineering-delivery roles requiring influence across teams.",
            },
        ),
    ]
)


EVENTS_SKILLS = OrderedDict(
    [
        (
            "Event Planning & Production",
            [
                "wedding planning",
                "event planning",
                "event design",
                "day-of coordination",
                "month-of coordination",
                "full-service planning",
                "run of show",
                "floor plans",
                "site visits",
                "venue tours",
                "event execution",
                "load-in",
                "setup",
                "teardown",
                "guest experience",
                "weddings",
                "corporate events",
                "social events",
                "galas",
                "trade show",
                "conferences",
                "banquet",
                "catering",
                "rentals",
            ],
        ),
        (
            "Sales & Client Experience",
            [
                "sales",
                "proposals",
                "contracts",
                "upselling",
                "client experience",
                "relationship management",
                "lead management",
                "CRM",
                "booking",
                "inquiries",
                "hospitality",
                "customer service",
                "account management",
                "quota",
            ],
        ),
        (
            "Vendor & Team Coordination",
            [
                "vendor sourcing",
                "vendor management",
                "vendor coordination",
                "negotiation",
                "staffing",
                "florals",
                "photographers",
                "audio visual",
                "AV",
                "bar service",
                "on-site point of contact",
                "cross-functional",
            ],
        ),
        (
            "Operations & Budgeting",
            [
                "budget",
                "budget control",
                "invoicing",
                "forecasting",
                "timelines",
                "logistics",
                "project coordination",
                "scheduling",
                "inventory",
                "permits",
                "insurance",
                "BEO",
                "banquet event order",
                "P&L",
            ],
        ),
        (
            "Tools & Systems",
            [
                "Tripleseat",
                "HoneyBook",
                "Aisle Planner",
                "Social Tables",
                "Cvent",
                "Eventbrite",
                "Delphi",
                "Canva",
                "Microsoft",
                "Adobe",
                "Excel",
                "Asana",
                "Monday.com",
                "Salesforce",
                "Google Workspace",
            ],
        ),
        (
            "Marketing & Content",
            [
                "social media",
                "content creation",
                "branding",
                "Instagram",
                "marketing",
                "photography",
                "email marketing",
                "collateral",
                "visual merchandising",
            ],
        ),
        (
            "Professional Strengths",
            [
                "attention to detail",
                "written communication",
                "organized",
                "calm under pressure",
                "multitasking",
                "problem solving",
                "leadership",
                "mentoring",
                "resourcefulness",
                "agility",
            ],
        ),
    ]
)


EVENTS_JOB_FAMILIES = OrderedDict(
    [
        (
            "Wedding & Event Coordination",
            {
                "terms": {
                    "wedding": 8,
                    "wedding coordinator": 10,
                    "event coordinator": 10,
                    "wedding planner": 9,
                    "day-of coordination": 6,
                    "month-of coordination": 6,
                    "event planning": 7,
                    "venue tours": 5,
                    "timelines": 3,
                    "vendor coordination": 5,
                    "guest experience": 4,
                    "couples": 4,
                },
                "description": "Wedding and social-event coordination roles owning planning through day-of execution.",
            },
        ),
        (
            "Venue & Catering Sales",
            {
                "terms": {
                    "sales": 6,
                    "venue": 7,
                    "catering": 6,
                    "catering sales": 9,
                    "event sales": 9,
                    "banquet": 5,
                    "proposals": 4,
                    "contracts": 4,
                    "tours": 4,
                    "inquiries": 4,
                    "booking": 4,
                    "client experience": 5,
                    "upselling": 3,
                },
                "description": "Venue, hotel, and catering sales roles that convert inquiries and tours into booked events.",
            },
        ),
        (
            "Corporate & Conference Event Management",
            {
                "terms": {
                    "corporate events": 8,
                    "conferences": 7,
                    "meeting planner": 8,
                    "trade show": 6,
                    "registration": 4,
                    "sponsorship": 4,
                    "logistics": 5,
                    "budget": 4,
                    "program management": 4,
                    "Cvent": 5,
                    "attendee": 4,
                },
                "description": "Corporate meeting, conference, and trade-show planning roles with heavier logistics and budget scope.",
            },
        ),
        (
            "Banquet & Food & Beverage Operations",
            {
                "terms": {
                    "banquet": 8,
                    "food and beverage": 7,
                    "catering manager": 8,
                    "bar service": 5,
                    "BEO": 6,
                    "banquet event order": 6,
                    "hospitality": 5,
                    "service staff": 4,
                    "restaurant": 4,
                    "hotel": 4,
                },
                "description": "Banquet, catering, and F&B operations roles inside hotels, clubs, and restaurant groups.",
            },
        ),
        (
            "Event Production & Operations",
            {
                "terms": {
                    "event production": 9,
                    "event operations": 8,
                    "load-in": 6,
                    "run of show": 6,
                    "audio visual": 5,
                    "staffing": 4,
                    "rentals": 5,
                    "floor plans": 5,
                    "setup": 4,
                    "vendor management": 5,
                    "on-site": 4,
                },
                "description": "Production and operations roles focused on build-out, logistics, and on-site execution.",
            },
        ),
        (
            "Event Marketing & Brand Experience",
            {
                "terms": {
                    "event marketing": 9,
                    "brand activation": 8,
                    "experiential": 8,
                    "social media": 5,
                    "content creation": 5,
                    "branding": 5,
                    "sponsorship": 4,
                    "visual merchandising": 6,
                    "trade show": 5,
                    "marketing": 4,
                },
                "description": "Experiential marketing and brand-activation roles that pair event execution with marketing output.",
            },
        ),
    ]
)


# Words that mark a job *title* as belonging to the domain at all. A "Sales Manager" listing
# matches plenty of resume skills without being an events job, so titles are checked separately.
DOMAIN_TITLE_TERMS = {
    "events": (
        "event", "events", "wedding", "weddings", "bridal", "catering", "caterer", "banquet",
        "venue", "meeting", "meetings", "conference", "conferences", "hospitality", "guest",
        "reception", "gala", "trade show", "tradeshow", "experiential", "activation", "hotel",
        "convention", "food and beverage",
    ),
    "technology": (
        "engineer", "engineering", "developer", "software", "platform", "infrastructure",
        "devops", "sre", "security", "data", "architect", "frontend", "front-end", "backend",
        "back-end", "full stack", "full-stack", "fullstack", "qa", "technical",
    ),
}

DOMAIN_SKILLS = {"technology": TECHNOLOGY_SKILLS, "events": EVENTS_SKILLS}
DOMAIN_JOB_FAMILIES = {"technology": TECHNOLOGY_JOB_FAMILIES, "events": EVENTS_JOB_FAMILIES}

# Terms that only really appear in one of the two domains, used to pick a lexicon.
DOMAIN_SIGNALS = {
    "technology": {
        "software": 4,
        "engineer": 4,
        "developer": 4,
        "kubernetes": 5,
        "typescript": 5,
        "javascript": 4,
        "python": 4,
        "terraform": 5,
        "api": 3,
        "ci/cd": 4,
        "devops": 5,
        "repository": 3,
        "deployment": 3,
    },
    "events": {
        "wedding": 6,
        "weddings": 6,
        "event planner": 6,
        "event coordinator": 6,
        "venue": 5,
        "catering": 5,
        "banquet": 5,
        "florals": 4,
        "guest experience": 4,
        "hospitality": 4,
        "couples": 4,
        "vendor sourcing": 4,
        "bridal": 5,
        "reception": 3,
    },
}


def count_term(text: str, term: str) -> int:
    escaped = re.escape(term.lower()).replace(r"\ ", r"\s+")
    return len(re.findall(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text, re.I))


def detect_domain(full_text: str) -> Tuple[str, Dict[str, int]]:
    lower = full_text.lower()
    scores = {
        domain: sum(weight * min(count_term(lower, term), 3) for term, weight in signals.items())
        for domain, signals in DOMAIN_SIGNALS.items()
    }
    best = max(scores, key=lambda domain: (scores[domain], domain == "technology"))
    return best, scores


@dataclass
class PageText:
    page: int
    text: str


@dataclass
class ResumeReport:
    source_file: str
    page_count: int
    extraction_method: str
    extraction_warnings: List[str] = field(default_factory=list)
    candidate: Dict[str, object] = field(default_factory=dict)
    domain: str = "technology"
    domain_scores: Dict[str, int] = field(default_factory=dict)
    sections: Dict[str, str] = field(default_factory=dict)
    raw_text: str = ""
    skills: Dict[str, List[str]] = field(default_factory=dict)
    experience: List[Dict[str, str]] = field(default_factory=list)
    education: List[str] = field(default_factory=list)
    projects: List[str] = field(default_factory=list)
    likely_next_job_types: List[Dict[str, object]] = field(default_factory=list)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


def column_bands(page: object, words: Sequence[Dict[str, object]]) -> List[Tuple[float, float]]:
    """Split a page into left-to-right column x-ranges.

    A gap only counts as a gutter when no word anywhere on the page crosses it, so
    tab-aligned date columns inside a single-column layout do not trigger a split.
    """
    left, right = float(page.bbox[0]), float(page.bbox[2])  # type: ignore[attr-defined]
    span = int(right - left) + 1
    if span <= 0:
        return [(left, right)]
    covered = bytearray(span)
    for word in words:
        start = max(0, int(float(word["x0"]) - left))  # type: ignore[arg-type]
        end = min(span - 1, int(float(word["x1"]) - left))  # type: ignore[arg-type]
        for x in range(start, end + 1):
            covered[x] = 1

    first, last = covered.find(1), covered.rfind(1)
    if first < 0:
        return [(left, right)]

    min_gutter = max(MIN_GUTTER_POINTS, int(span * 0.03))
    min_column = int(span * 0.10)
    bands: List[Tuple[float, float]] = []
    cursor = first
    x = first
    while x <= last:
        if covered[x]:
            x += 1
            continue
        gap_start = x
        while x <= last and not covered[x]:
            x += 1
        if x - gap_start >= min_gutter and gap_start - cursor >= min_column:
            bands.append((left + cursor, left + gap_start))
            cursor = x
    bands.append((left + cursor, left + last + 1))
    return [band for band in bands if band[1] - band[0] >= min_column] or [(left, right)]


def page_text(page: object) -> str:
    """Extract one page, reading each column top-to-bottom before moving right."""
    words = page.extract_words(x_tolerance=X_TOLERANCE)  # type: ignore[attr-defined]
    bands = column_bands(page, words)
    if len(bands) < 2:
        return page.extract_text(x_tolerance=X_TOLERANCE, y_tolerance=Y_TOLERANCE) or ""  # type: ignore[attr-defined]

    top, bottom = float(page.bbox[1]), float(page.bbox[3])  # type: ignore[attr-defined]
    chunks: List[str] = []
    for x0, x1 in bands:
        cropped = page.crop((x0, top, x1, bottom))  # type: ignore[attr-defined]
        chunk = cropped.extract_text(x_tolerance=X_TOLERANCE, y_tolerance=Y_TOLERANCE) or ""
        if chunk.strip():
            chunks.append(chunk)
    return "\n".join(chunks)


def extract_pages(pdf_path: Path) -> Tuple[List[PageText], str, List[str]]:
    warnings: List[str] = []
    try:
        import pdfplumber  # type: ignore

        pages: List[PageText] = []
        with pdfplumber.open(pdf_path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                pages.append(PageText(index, page_text(page)))
        method = "pdfplumber"
    except Exception as pdfplumber_error:
        warnings.append(f"pdfplumber extraction failed: {pdfplumber_error}")
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(pdf_path))
            pages = [PageText(i, page.extract_text() or "") for i, page in enumerate(reader.pages, start=1)]
            method = "pypdf fallback"
        except Exception as pypdf_error:
            raise RuntimeError(
                "Could not extract text. Install dependencies with: "
                "python3 -m pip install pdfplumber pypdf"
            ) from pypdf_error

    total_chars = sum(len(page.text.strip()) for page in pages)
    if total_chars < 200:
        warnings.append(
            "Very little text was extracted. This PDF may be scanned/image-based; run OCR before analysis."
        )
    for page in pages:
        if len(page.text.strip()) < 40:
            warnings.append(f"Page {page.page} yielded very little text ({len(page.text.strip())} characters).")
    return pages, method, warnings


def lines_from_pages(pages: Sequence[PageText]) -> List[str]:
    lines: List[str] = []
    for page in pages:
        for raw_line in page.text.splitlines():
            line = normalize_space(raw_line)
            if line:
                lines.append(line)
    return lines


def canonical_heading(line: str) -> Optional[str]:
    cleaned = re.sub(r"[^a-z ]", "", line.lower()).strip()
    return SECTION_NAMES.get(cleaned)


def split_sections(lines: Sequence[str]) -> Dict[str, str]:
    sections: Dict[str, List[str]] = OrderedDict()
    current = "header"
    sections[current] = []
    for line in lines:
        heading = canonical_heading(line)
        if heading:
            current = heading
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)
    return {name: "\n".join(values).strip() for name, values in sections.items() if values}


NON_NAME_WORDS = ("resume", "curriculum", "vitae", "dear", "objective", "summary", "education", "skills", "experience")


def looks_like_name(line: str) -> bool:
    tokens = line.split()
    if not 1 <= len(tokens) <= 4:
        return False
    if any(char.isdigit() for char in line) or "@" in line or FULL_DATE_RE.match(line):
        return False
    if any(word in line.lower() for word in NON_NAME_WORDS):
        return False
    return all(NAME_TOKEN_RE.match(token) for token in tokens)


def extract_name(lines: Sequence[str]) -> str:
    header = list(lines[: min(18, len(lines))])
    for index, line in enumerate(header):
        if not looks_like_name(line):
            continue
        # Stacked display headers put the given name and surname on separate lines.
        if len(line.split()) == 1:
            following = header[index + 1] if index + 1 < len(header) else ""
            if looks_like_name(following) and len(following.split()) == 1:
                return f"{line} {following}"
        return line
    return ""


def extract_headline(lines: Sequence[str], name: str) -> str:
    """The role descriptor a resume prints under the name, e.g. 'Event Planner & Coordinator'."""
    header = list(lines[: min(18, len(lines))])
    name_tail = name.split()[-1].lower() if name else ""
    for index, line in enumerate(header):
        if name_tail and name_tail in line.lower():
            for candidate in header[index + 1 : index + 4]:
                if EMAIL_RE.search(candidate) or PHONE_RE.search(candidate) or FULL_DATE_RE.match(candidate):
                    continue
                if 3 < len(candidate) <= 70 and not any(char.isdigit() for char in candidate):
                    return candidate
            break
    return ""


def extract_contact(lines: Sequence[str], full_text: str) -> Dict[str, object]:
    name = extract_name(lines)

    emails = sorted(set(EMAIL_RE.findall(full_text)))
    phones = sorted(set(normalize_space(match) for match in PHONE_RE.findall(full_text)))
    urls = []
    for match in URL_RE.findall(full_text):
        clean = match.rstrip(".,;:)")
        if clean not in urls and len(clean) > 5:
            urls.append(clean)

    locations = []
    for match in LOCATION_RE.findall(full_text):
        value = normalize_space(match)
        if value not in locations:
            locations.append(value)

    remote_preference = bool(re.search(r"\bremote\b", full_text, re.I))
    return {
        "name": name,
        "headline": extract_headline(lines, name),
        "emails": emails,
        "phones": phones,
        "urls": urls,
        "locations": locations,
        "remote_signal": remote_preference,
    }


def find_terms(text: str, terms: Iterable[str]) -> List[str]:
    found: List[str] = []
    lower_text = text.lower()
    for term in terms:
        pattern = re.escape(term.lower()).replace(r"\ ", r"\s+")
        if re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", lower_text, re.I):
            found.append(term)
    return found


def extract_skills(sections: Dict[str, str], full_text: str, domain: str) -> Dict[str, List[str]]:
    skills: Dict[str, List[str]] = OrderedDict()
    skill_text = sections.get("skills", "")
    for category, terms in DOMAIN_SKILLS[domain].items():
        found = find_terms(skill_text or full_text, terms)
        if found:
            skills[category] = found

    # Preserve explicit resume labels, even when a label is outside the lexicon.
    for line in skill_text.splitlines():
        match = re.match(r"^([^:]{2,45}):\s*(.+)$", line)
        if match:
            label, values = normalize_space(match.group(1)), normalize_space(match.group(2))
            if label not in skills and values:
                skills[label] = [item.strip() for item in re.split(r",\s*", values) if item.strip()]
    return skills


def parse_experience(experience_text: str) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    lines = [line for line in experience_text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        match = DATE_RANGE_RE.search(line)
        if not match:
            continue
        before = normalize_space(line[: match.start()].strip(" -–—|,·•"))
        after = normalize_space(line[match.end() :].strip(" -–—|,·•"))
        if before:
            title, company = before, after
        else:
            # Stacked layouts print the title above the date range and the employer below it.
            title = lines[index - 1] if index else ""
            company = after or (lines[index + 1] if index + 1 < len(lines) else "")
        if not title:
            continue
        entries.append(
            {
                "title": title,
                "company": company,
                "date_range": normalize_space(match.group(0)),
            }
        )
    return entries


def extract_education(education_text: str) -> List[str]:
    return [line for line in education_text.splitlines() if line.strip()]


def extract_projects(projects_text: str) -> List[str]:
    return [line for line in projects_text.splitlines() if line.strip()]


def compact_snippet(text: str, term: str, limit: int = 180) -> str:
    lower_text = text.lower()
    position = lower_text.find(term.lower())
    if position < 0:
        return normalize_space(text[:limit])
    start = max(0, position - 65)
    end = min(len(text), position + len(term) + 115)
    snippet = normalize_space(text[start:end])
    return ("..." if start else "") + snippet + ("..." if end < len(text) else "")


def score_job_families(full_text: str, domain: str) -> List[Dict[str, object]]:
    lower_text = full_text.lower()
    results: List[Dict[str, object]] = []
    for family, config in DOMAIN_JOB_FAMILIES[domain].items():
        score = 0
        evidence: List[str] = []
        for term, weight in config["terms"].items():
            count = count_term(lower_text, term)
            if count:
                contribution = weight * min(count, 3)
                score += contribution
                if len(evidence) < 6:
                    evidence.append(term)
        if score:
            evidence_text = []
            for term in evidence[:3]:
                evidence_text.append(compact_snippet(full_text, term))
            results.append(
                {
                    "job_family": family,
                    "score": score,
                    "description": config["description"],
                    "matched_terms": evidence,
                    "evidence": evidence_text,
                }
            )

    results.sort(key=lambda item: (-int(item["score"]), str(item["job_family"])))
    total = sum(int(item["score"]) for item in results) or 1
    for item in results:
        share = int(item["score"]) / total
        item["confidence"] = round(min(0.99, 0.45 + share * 0.9), 2)
    return results


def infer_seniority(full_text: str) -> Optional[str]:
    lower = full_text.lower()
    if re.search(r"\b(principal|staff|architect)\b", lower):
        return "Staff/principal-level signals"
    if re.search(r"\bsenior\b", lower):
        return "Senior-level signals"
    if re.search(r"\b(lead|manager|director)\b", lower):
        return "Lead/management-level signals"
    return None


def analyze_resume(pdf_path: Path, domain: Optional[str] = None) -> ResumeReport:
    pages, method, warnings = extract_pages(pdf_path)
    lines = lines_from_pages(pages)
    full_text = "\n".join(page.text for page in pages)
    sections = split_sections(lines)
    candidate = extract_contact(lines, full_text)
    candidate["seniority_signal"] = infer_seniority(full_text)
    candidate["current_role_signal"] = next(
        (entry["title"] for entry in parse_experience(sections.get("experience", ""))[:1]), None
    )

    detected, domain_scores = detect_domain(full_text)
    resolved_domain = domain or detected

    section_text = dict(sections)
    recommendations = score_job_families(full_text, resolved_domain)
    if not recommendations:
        warnings.append("No job-family matches were found; add industry-specific terms or inspect the extracted text.")

    return ResumeReport(
        source_file=str(pdf_path.expanduser().resolve()),
        page_count=len(pages),
        extraction_method=method,
        extraction_warnings=warnings,
        candidate=candidate,
        domain=resolved_domain,
        domain_scores=domain_scores,
        sections=section_text,
        raw_text=full_text,
        skills=extract_skills(sections, full_text, resolved_domain),
        experience=parse_experience(sections.get("experience", "")),
        education=extract_education(sections.get("education", "")),
        projects=extract_projects(sections.get("projects", "")),
        likely_next_job_types=recommendations[:5],
    )


def render_text(report: ResumeReport) -> str:
    data = asdict(report)
    candidate = data["candidate"]
    lines = [
        "Resume Job Analysis",
        "=" * 20,
        f"Source: {data['source_file']}",
        f"Pages: {data['page_count']} | Extraction: {data['extraction_method']}",
        f"Domain: {data['domain']} (signals: {data['domain_scores']})",
        "",
        "Candidate",
        "---------",
        f"Name: {candidate.get('name') or 'Not detected'}",
        f"Headline: {candidate.get('headline') or 'Not detected'}",
        f"Email: {', '.join(candidate.get('emails', [])) or 'Not detected'}",
        f"Phone: {', '.join(candidate.get('phones', [])) or 'Not detected'}",
        f"Location: {', '.join(candidate.get('locations', [])) or 'Not detected'}",
        f"Remote signal: {'yes' if candidate.get('remote_signal') else 'no'}",
        f"Seniority signal: {candidate.get('seniority_signal') or 'Not detected'}",
        f"Current-role signal: {candidate.get('current_role_signal') or 'Not detected'}",
        "",
        "Likely next job types",
        "--------------------",
    ]
    for index, item in enumerate(data["likely_next_job_types"], start=1):
        lines.append(
            f"{index}. {item['job_family']} — confidence {item['confidence']:.0%} (score {item['score']})"
        )
        lines.append(f"   {item['description']}")
        lines.append(f"   Matched: {', '.join(item['matched_terms'])}")
        if item["evidence"]:
            lines.append(f"   Evidence: {item['evidence'][0]}")

    lines.extend(["", "Extracted skills", "-----------------"])
    for category, values in data["skills"].items():
        lines.append(f"{category}: {', '.join(values)}")

    lines.extend(["", "Experience entries", "------------------"])
    for entry in data["experience"]:
        company = f" — {entry['company']}" if entry.get("company") else ""
        lines.append(f"- {entry['title']}{company} ({entry['date_range']})")

    if data["extraction_warnings"]:
        lines.extend(["", "Warnings", "--------"])
        lines.extend(f"- {warning}" for warning in data["extraction_warnings"])
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Extract and classify a resume PDF locally.")
    parser.add_argument("pdf", type=Path, help="Path to a resume PDF")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of a readable report")
    parser.add_argument("--output", type=Path, help="Write the report to this file instead of stdout")
    parser.add_argument(
        "--domain",
        choices=sorted(DOMAIN_SKILLS),
        help="Override the auto-detected resume domain",
    )
    args = parser.parse_args(argv)

    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.is_file():
        parser.error(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        parser.error("Input must be a PDF file")

    try:
        report = analyze_resume(pdf_path, args.domain)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    rendered = json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n" if args.json else render_text(report)
    if args.output:
        args.output.expanduser().resolve().write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
