from __future__ import annotations

import html
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resume_job_analyzer import DOMAIN_TITLE_TERMS, ResumeReport, analyze_resume  # noqa: E402


def load_env_file(path: Path = ROOT / ".env.local") -> None:
    """Read KEY=value pairs into the environment, leaving any real env var as the winner."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env_file()


HEADERS = {
    "User-Agent": "job-search-research/1.0 (public job discovery; local resume matching)",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetched_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(url: str, *, timeout: int = 25, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    response = requests.get(url, headers=HEADERS, timeout=timeout, params=params)
    response.raise_for_status()
    return response


def clean_html(value: str) -> str:
    soup = BeautifulSoup(html.unescape(value or ""), "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def absolute(base: str, href: str) -> str:
    return urljoin(base, href)


def location_text(value: Any) -> str:
    """Turn schema.org location objects into a readable location string."""
    if isinstance(value, list):
        return "; ".join(filter(None, (location_text(item) for item in value)))
    if isinstance(value, dict):
        address = value.get("address", value)
        if isinstance(address, dict):
            parts = [address.get(key, "") for key in ("addressLocality", "addressRegion", "addressCountry")]
            return ", ".join(str(part) for part in parts if part)
        return str(address)
    return str(value or "")


def schema_text(value: Any) -> str:
    """Flatten common schema.org scalar objects such as salary ranges."""
    if isinstance(value, dict):
        prefix = "$" if value.get("currency") == "USD" else ""
        unit = value.get("unitText", "")
        if "minValue" in value and "maxValue" in value:
            return f"{prefix}{value.get('minValue')}-{prefix}{value.get('maxValue')} {unit}".strip()
        if "value" in value:
            value_text = schema_text(value.get("value"))
            return f"{prefix}{value_text} {unit}".strip() if prefix and not value_text.startswith("$") else f"{value_text} {unit}".strip()
        return ", ".join(schema_text(v) for v in value.values() if v)
    if isinstance(value, list):
        return "; ".join(schema_text(v) for v in value if v)
    return str(value or "")


def job(
    *,
    source: str,
    title: str,
    company: str = "",
    url: str,
    description: str = "",
    location: str = "",
    posted: str = "",
    salary: str = "",
    tags: Optional[Iterable[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "source": source,
        "title": " ".join((title or "").split()),
        "company": " ".join((company or "").split()),
        "url": url,
        "description": clean_html(description),
        "location": " ".join((location or "").split()),
        "posted": " ".join((posted or "").split()),
        "salary": " ".join((salary or "").split()),
        "tags": list(tags or []),
        "metadata": metadata or {},
        "scraped_at": fetched_at(),
    }


def result(source: str, jobs: Sequence[Dict[str, Any]], errors: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "source": source,
        "scraped_at": fetched_at(),
        "jobs": list(jobs),
        "errors": errors or [],
    }


def save_or_print(payload: Dict[str, Any], output: Optional[str] = None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if output:
        Path(output).expanduser().resolve().write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def load_report(resume_path: str, domain: Optional[str] = None) -> ResumeReport:
    return analyze_resume(Path(resume_path).expanduser().resolve(), domain)


def _contains(text: str, term: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])", text.lower()))


# Towns a candidate searching a given metro would reasonably commute to, plus the state name
# so listings that only say "Colorado" still register as in-region.
METRO_AREAS: Dict[str, Tuple[str, ...]] = {
    "denver": (
        "Colorado", "Aurora", "Lakewood", "Littleton", "Englewood", "Centennial", "Arvada",
        "Westminster", "Thornton", "Broomfield", "Golden", "Wheat Ridge", "Boulder", "Louisville",
        "Lafayette", "Superior", "Commerce City", "Northglenn", "Greenwood Village",
        "Highlands Ranch", "Parker", "Castle Rock", "Brighton", "Lone Tree", "Morrison",
        "Evergreen", "Erie", "Longmont", "Cherry Creek", "Glendale",
    ),
    "columbus": (
        "Ohio", "Dublin", "Westerville", "Worthington", "Upper Arlington", "Grandview Heights",
        "Hilliard", "Gahanna", "Bexley", "New Albany", "Powell", "Delaware", "Grove City",
        "Reynoldsburg", "Pickerington", "Lewis Center", "Marysville",
    ),
}

STATE_ABBREVIATIONS = {"denver": "CO", "columbus": "OH"}

# Listings scoring below this share of the best match are dropped rather than padding the list.
RELEVANCE_FLOOR_RATIO = 0.55

ROLE_NOUNS = (
    "coordinator", "planner", "manager", "director", "specialist", "lead", "supervisor",
    "producer", "consultant", "executive", "engineer", "architect", "designer", "analyst",
)

REMOTE_STRONG_RE = re.compile(
    r"100%\s+remote|fully remote|remote only|remote position|remote role|work from anywhere|"
    r"remote \(work from home\)|hiring remotely|remote work policy",
    re.I,
)
HYBRID_RE = re.compile(r"\bhybrid\b", re.I)
# In a terse job title these words mean the role itself is remote, unlike in body copy where
# "virtual events" or "remote venue" may just describe the work.
REMOTE_TITLE_RE = re.compile(r"\bvirtual\b|\bremote\b|work from home|\btelecommute\b", re.I)
WEAK_REMOTE_RE = re.compile(r"\bremote(?:ly)?\b|work from home|\btelecommute\b|\bvirtual\b", re.I)

# Hourly support titles. These share vocabulary with event-management roles ("banquet",
# "event staff") but sit well below a planner or coordinator who runs teams and budgets.
SUPPORT_TITLE_RE = re.compile(
    r"\bserver\b|\bservers\b|event staff|\bstaff\b\s*-|\battendant\b|\bcustodian\b|\bdishwasher\b|"
    r"\bhost(?:ess)?\b|\bbusser\b|\bbarback\b|\bbartender\b|\bcashier\b|\bgreeter\b|\busher\b|"
    r"brand ambassador|\bpromoter\b|promotions representative|\bdemonstrator\b|crew member|"
    r"set[- ]?up crew|\bline cook\b|\bdriver\b",
    re.I,
)
ONSITE_RE = re.compile(r"\bon-?site\b|\bin[- ]person\b|\bin[- ]office\b", re.I)


SALARY_NUMBER_RE = re.compile(r"([\d,]+(?:\.\d+)?)")
HOURLY_HINT_RE = re.compile(r"hour|hourly|/\s*hr|per hr", re.I)
WEEKLY_HINT_RE = re.compile(r"week", re.I)
MONTHLY_HINT_RE = re.compile(r"month", re.I)
FULL_TIME_HOURS_PER_YEAR = 2080


def annual_salary(text: str) -> Optional[float]:
    """Annualise a board's salary string, taking the top of any range.

    Boards publish wildly different shapes ("$105,000.00-$110,000.00 yearly", "$17.42 hourly",
    "$55,754 per year (estimated by Adzuna)"). The top of a range answers the question a candidate
    actually asks of a salary floor: could this role pay at least that much?
    """
    if not text:
        return None
    numbers = [float(value.replace(",", "")) for value in SALARY_NUMBER_RE.findall(text)]
    numbers = [value for value in numbers if value > 0]
    if not numbers:
        return None
    top = max(numbers)
    if HOURLY_HINT_RE.search(text):
        return top * FULL_TIME_HOURS_PER_YEAR
    if WEEKLY_HINT_RE.search(text):
        return top * 52
    if MONTHLY_HINT_RE.search(text):
        return top * 12
    return top


def filter_by_salary(
    jobs: Sequence[Dict[str, Any]], min_salary: float
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Drop listings that cannot clear a salary floor, reporting why they were dropped."""
    if not min_salary:
        return list(jobs), 0, 0
    kept: List[Dict[str, Any]] = []
    below = unstated = 0
    for item in jobs:
        value = annual_salary(str(item.get("salary", "")))
        if value is None:
            unstated += 1
        elif value < min_salary:
            below += 1
        else:
            kept.append(item)
    return kept, below, unstated


@dataclass
class SearchPreferences:
    """What the candidate is actually looking for, independent of what the resume says."""

    location: str = ""
    work_model: str = "any"  # onsite | hybrid | remote | any
    radius_miles: int = 50
    min_salary: float = 0.0
    roles: Tuple[str, ...] = ()

    @property
    def city(self) -> str:
        return self.location.split(",")[0].strip()

    @property
    def state(self) -> str:
        parts = [part.strip() for part in self.location.split(",")]
        if len(parts) > 1 and parts[1]:
            return parts[1]
        return STATE_ABBREVIATIONS.get(self.city.lower(), "")

    @property
    def nearby(self) -> Tuple[str, ...]:
        return METRO_AREAS.get(self.city.lower(), ())


def work_model(item: Dict[str, Any]) -> str:
    """Classify a listing as Onsite / Hybrid / Remote, preferring an explicit ATS field."""
    declared = str(item.get("metadata", {}).get("workplace", "")).lower().replace("-", "_")
    if declared in ("on_site", "onsite"):
        return "Onsite"
    if declared == "hybrid":
        return "Hybrid"
    if declared == "remote":
        return "Remote"

    if REMOTE_TITLE_RE.search(str(item.get("title", ""))):
        return "Remote"

    text = " ".join(str(item.get(key, "")) for key in ("title", "location", "description"))
    remote = bool(REMOTE_STRONG_RE.search(text))
    hybrid = bool(HYBRID_RE.search(text))
    if remote and hybrid:
        return "Hybrid"
    if remote:
        return "Remote"
    if hybrid:
        return "Hybrid"
    if ONSITE_RE.search(text):
        return "Onsite"
    # Never assert onsite over any remote language, even language too weak to assert remote.
    if WEAK_REMOTE_RE.search(text):
        return "Unclear"
    # A concrete city with no remote language is an in-person posting in practice.
    if re.search(r"\b[A-Z][a-z]+,\s*[A-Z]{2}\b", str(item.get("location", ""))):
        return "Onsite"
    return "Unclear"


def score_job(
    item: Dict[str, Any], report: ResumeReport, preferences: Optional[SearchPreferences] = None
) -> Dict[str, Any]:
    preferences = preferences or SearchPreferences()
    title = item.get("title", "")
    body = " ".join(str(item.get(key, "")) for key in ("title", "description", "tags", "location"))
    lower = body.lower()
    score = 0.0
    matched: List[str] = []
    notes: List[str] = []

    profile_terms: List[str] = []
    for values in report.skills.values():
        profile_terms.extend(values)
    for recommendation in report.likely_next_job_types[:4]:
        profile_terms.extend(recommendation.get("matched_terms", []))

    seen = set()
    body_score = 0.0
    for term in profile_terms:
        key = term.lower()
        if key in seen or len(key) < 3:
            continue
        seen.add(key)
        if _contains(title, term):
            score += 2.5
        elif _contains(lower, term):
            body_score += 1.0
        else:
            continue
        matched.append(term)
    score += body_score

    # A title matching the candidate's strongest role family beats one that merely shares the
    # domain: "Wedding Coordinator" fits a wedding planner better than "Airline Catering Manager".
    # Only distinctive terms qualify: a family's matched terms include generic business words like
    # "sales", which would hand this bonus to every unrelated sales job.
    title_terms = DOMAIN_TITLE_TERMS.get(report.domain, ())
    family_terms: List[str] = []
    for recommendation in report.likely_next_job_types[:2]:
        for term in recommendation.get("matched_terms", []):
            if " " in term or term.lower() in title_terms:
                family_terms.append(term)
    if family_terms and any(_contains(title, term) for term in family_terms):
        score += 5
        notes.append("matches strongest resume role family")

    if title_terms:
        if any(_contains(title, term) for term in title_terms):
            score += 4
            notes.append("on-domain title")
        else:
            score -= 7
            notes.append("off-domain title")

    senior = bool(re.search(r"\b(senior|staff|principal|lead|architect|manager|director)\b", report.raw_text, re.I))
    if senior and re.search(r"\b(senior|staff|principal|lead|architect|manager|director)\b", title, re.I):
        score += 5
        notes.append("seniority alignment")
    if senior and re.search(r"\b(intern|internship|junior|entry[- ]level)\b", title, re.I):
        score -= 8
        notes.append("below target seniority")
    if SUPPORT_TITLE_RE.search(title):
        score -= 11
        notes.append("hourly support role below current level")
    if re.search(r"part[- ]time|seasonal|temporary|\btemp\b|\bintern\b", f"{title} {item.get('salary', '')}", re.I):
        score -= 6
        notes.append("part-time, seasonal, or temporary")

    # The seniority bonus above only fires on manager/director wording, which would bury lateral
    # moves for someone whose own title is "Coordinator". Reward the candidate's own role level too.
    own_title = f"{report.candidate.get('headline', '')} {report.candidate.get('current_role_signal') or ''}"
    own_roles = [noun for noun in ROLE_NOUNS if _contains(own_title, noun)]
    if own_roles and any(_contains(title, noun) for noun in own_roles):
        score += 4
        notes.append("title matches the candidate's own role level")

    model = work_model(item)
    wanted = preferences.work_model.lower()
    if wanted in ("onsite", "hybrid", "remote"):
        target = wanted.capitalize()
        if model == target:
            score += 6
            notes.append(f"{model.lower()} alignment")
        elif model == "Unclear":
            score -= 1
            notes.append("work model not stated")
        elif wanted == "onsite" and model == "Hybrid":
            score += 2
            notes.append("hybrid acceptable for in-person search")
        else:
            score -= 8
            notes.append(f"{model.lower()} conflicts with {wanted} search")

    if preferences.location:
        location_text_value = f"{item.get('location', '')} {item.get('title', '')}"
        if preferences.city and re.search(rf"\b{re.escape(preferences.city)}\b", location_text_value, re.I):
            score += 7
            notes.append(f"{preferences.city} location match")
        elif any(re.search(rf"\b{re.escape(town)}\b", location_text_value, re.I) for town in preferences.nearby):
            score += 5
            notes.append("metro-area location match")
        elif preferences.state and re.search(rf"\b{re.escape(preferences.state)}\b", location_text_value):
            score += 4
            notes.append(f"{preferences.state} location match")
        elif re.search(r"\b[A-Z][a-z]+,\s*[A-Z]{2}\b", str(item.get("location", ""))):
            score -= 9
            notes.append("outside target metro")
        else:
            score -= 1
            notes.append("location not stated")

    suspicious = bool(
        re.search(
            r"please mention the word|tag [A-Za-z0-9_.-]+ when applying|crypto investment|data annotation|pay to apply|buy equipment",
            lower,
        )
    )
    if suspicious:
        score -= 20
        notes.append("suspicious/low-signal wording")

    if report.domain == "technology" and re.search(r"\bc#\b|\.net", title, re.I) and not re.search(
        r"\bc#\b|\.net", report.raw_text, re.I
    ):
        score -= 7
        notes.append("primary-language mismatch")

    source_adjustment = {
        "Workable": 2,
        "Adzuna": 1,
        "Talent.com": 0,
        "Built In": 3,
        "Y Combinator Jobs": 2,
        "Wellfound": 2,
        "Dice": -2,
        "Remote OK": -2,
    }.get(str(item.get("source", "")), 0)
    score += source_adjustment
    if source_adjustment:
        notes.append(f"{item.get('source')} source adjustment")

    item = dict(item)
    item["fit_score"] = round(score, 2)
    item["work_model"] = model
    item["matched_resume_signals"] = matched[:12]
    item["scoring_notes"] = notes
    item["suspicious_low_signal"] = suspicious
    return item


def rank_jobs(
    jobs: Sequence[Dict[str, Any]],
    report: ResumeReport,
    limit: int = 10,
    max_per_source: Optional[int] = 3,
    preferences: Optional[SearchPreferences] = None,
) -> List[Dict[str, Any]]:
    scored = [score_job(item, report, preferences) for item in jobs]
    deduped: Dict[str, Dict[str, Any]] = {}
    for item in scored:
        # Job boards often syndicate the same requisition through multiple staffing firms.
        key = re.sub(r"[^a-z0-9]", "", f"{item.get('title','')} {item.get('company','')}".lower())
        if key not in deduped or item["fit_score"] > deduped[key]["fit_score"]:
            deduped[key] = item
    ordered = sorted(deduped.values(), key=lambda item: (-item["fit_score"], item.get("company", "")))
    # Return a short strong list rather than padding to --limit with weak matches.
    if ordered and ordered[0]["fit_score"] > 0:
        floor = ordered[0]["fit_score"] * RELEVANCE_FLOOR_RATIO
        ordered = [item for item in ordered if item["fit_score"] >= floor]
    selected: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    for item in ordered:
        source = str(item.get("source", "Unknown"))
        if max_per_source is not None and counts.get(source, 0) >= max_per_source:
            continue
        counts[source] = counts.get(source, 0) + 1
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def json_ld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(node.string or node.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values = value if isinstance(value, list) else [value]
        for record in values:
            if isinstance(record, dict) and record.get("@graph"):
                records.extend(x for x in record["@graph"] if isinstance(x, dict))
            elif isinstance(record, dict):
                records.append(record)
    return records
