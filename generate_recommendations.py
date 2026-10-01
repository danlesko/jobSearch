#!/usr/bin/env python3
"""Turn job_scrapers.run_all JSON into a human-readable recommendation report."""

from __future__ import annotations

import argparse
import ast
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


DOMAIN_SCOPE = {
    "events": "Event coordination, wedding and venue sales, catering and banquet, and event production roles.",
    "technology": "Senior software, frontend/full-stack, platform/cloud, security, infrastructure, and engineering-quality roles.",
}

SOURCE_CAVEATS = {
    "Workable": "Workable surfaces listings from employers' own hiring pages; confirm the role is still open and that the posted city matches where you would actually work.",
    "Adzuna": "Adzuna links through to the original posting rather than hosting it, and fills in a salary range when the employer omits one — treat any figure marked estimated as Adzuna's guess, not the employer's offer.",
    "Talent.com": "Talent.com aggregates from many feeds, so postings can be stale or reposted by a staffing agency rather than the employer; check the date and confirm the role on the employer's own site.",
    "Dice": "Dice has many staffing/recruiter listings; verify the end client, employment type, and work arrangement.",
    "Wellfound": "Verify that the startup is still actively hiring and that the listed remote/visa policy fits.",
    "Y Combinator Jobs": "YC startup roles can move quickly; verify location, visa eligibility, and current opening status.",
    "Built In": "Confirm the detailed listing's location and remote policy before investing in an application.",
}


def flatten(value: Any) -> str:
    if isinstance(value, str) and value.startswith("{") and "'@type'" in value:
        try:
            return flatten(ast.literal_eval(value))
        except (ValueError, SyntaxError):
            pass
    if isinstance(value, dict):
        if "minValue" in value or "maxValue" in value or "value" in value:
            minimum = value.get("minValue")
            maximum = value.get("maxValue")
            exact = value.get("value")
            unit = value.get("unitText", "")
            if isinstance(exact, dict):
                exact = exact.get("value")
            if minimum is not None and maximum is not None:
                return f"${minimum:,.0f}-${maximum:,.0f} {unit}".strip()
            if exact is not None:
                return f"${exact:,.0f} {unit}".strip() if isinstance(exact, (int, float)) else str(exact)
        return ", ".join(flatten(v) for v in value.values() if v)
    if isinstance(value, list):
        return "; ".join(flatten(v) for v in value if v)
    return str(value or "").strip()


def format_posted(value: str) -> str:
    if not value:
        return "Not exposed by the page"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%b %-d, %Y")
    except ValueError:
        return value


def reason(job: Dict[str, Any]) -> str:
    matched = job.get("matched_resume_signals", [])
    positives = [note for note in job.get("scoring_notes", []) if "conflict" not in note and "not stated" not in note]
    parts = []
    if matched:
        parts.append("resume overlap: " + ", ".join(matched[:8]))
    if positives:
        parts.append("plus " + ", ".join(positives[:4]))
    if not parts:
        return "Title and role-family alignment with the resume profile."
    return (parts[0][0].upper() + parts[0][1:]) + ("; " + parts[1] if len(parts) > 1 else "") + "."


def caveat(job: Dict[str, Any], search: Dict[str, Any]) -> str:
    base = SOURCE_CAVEATS.get(
        str(job.get("source", "")), "Verify the live posting and employer careers page before applying."
    )
    model = job.get("work_model", "Unclear")
    wanted = str(search.get("work_model", "any"))
    if wanted != "any" and model.lower() != wanted:
        if model == "Unclear":
            base += f" This listing does not state whether it is {wanted}; confirm the arrangement early."
        else:
            base += f" It reads as {model.lower()} rather than {wanted}."
    conflicts = [note for note in job.get("scoring_notes", []) if "conflict" in note or "outside" in note]
    if conflicts:
        base += " Flagged: " + ", ".join(conflicts) + "."
    if re.search(r"contract|contractor|seasonal|part[- ]time", str(job.get("title", "")), re.I):
        base += " The title suggests contract, seasonal, or part-time terms."
    return base


def render(data: Dict[str, Any]) -> str:
    today = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    recommendations: List[Dict[str, Any]] = data.get("recommendations", [])
    search = data.get("search", {})
    name = data.get("candidate_name") or "this candidate"
    domain = str(data.get("domain", ""))
    location = search.get("location") or "Not restricted"
    work_model = search.get("work_model", "any")
    min_salary = float(search.get("min_salary") or 0)
    salary_filter = data.get("salary_filter") or {}

    lines = [
        f"# Job recommendations for {name.title() if name.isupper() else name}",
        "",
        f"**Generated:** {today}  ",
        f"**Resume:** `{data.get('resume', '')}`  ",
        f"**Target location:** {location} (within {search.get('radius_miles', 50)} miles)  ",
        f"**Preferred work model:** {work_model}  ",
        f"**Salary floor:** {f'${min_salary:,.0f} per year' if min_salary else 'none'}  ",
        f"**Public postings scraped:** {data.get('scraped_job_count', 0)}  ",
        f"**Scope:** {DOMAIN_SCOPE.get(domain, 'Roles matching the resume profile.')}",
        "",
        "These are ranked matches to the resume profile, not guaranteed endorsements. Ranking favors the "
        "resume's own experience and skills and the target location"
        + (
            ", with no preference between on-site, hybrid, and remote. "
            if work_model == "any"
            else f", and prefers {work_model} roles. "
        )
        + "Check the live posting and apply through the employer's official flow before submitting.",
        "",
        f"## Top {len(recommendations)} to review",
        "",
    ]
    for index, job in enumerate(recommendations, 1):
        salary = flatten(job.get("salary")) or "Not stated"
        job_location = flatten(job.get("location")) or "Not stated"
        posted = format_posted(job.get("posted", ""))
        lines.extend(
            [
                f"### {index}. [{job.get('title', 'Untitled')}]({job.get('url')})",
                "",
                f"- **Company:** {job.get('company') or 'Not stated'}",
                f"- **Source:** {job.get('source')}",
                f"- **Work model:** {job.get('work_model', 'Unclear')}",
                f"- **Location:** {job_location}",
                f"- **Compensation:** {salary}",
                f"- **Posted/updated:** {posted}",
                f"- **Resume fit score:** {job.get('fit_score')}",
                f"- **Why it fits:** {reason(job)}",
                f"- **Caveat:** {caveat(job, search)}",
                "",
            ]
        )

    if min_salary:
        lines.extend(
            [
                "## Effect of the salary floor",
                "",
                f"- **Cleared ${min_salary:,.0f}:** {salary_filter.get('eligible', 0)} listings",
                f"- **Below the floor:** {salary_filter.get('dropped_below_floor', 0)} dropped",
                f"- **No salary published:** {salary_filter.get('dropped_unstated_salary', 0)} dropped "
                "— these are excluded because the floor cannot be verified, not because they pay badly. "
                "Re-run without `--min-salary` to see them.",
                "",
                "A range counts if its **top** clears the floor, so some of these roles may start lower. "
                "Hourly rates are annualised at 2,080 hours.",
                "",
            ]
        )

    lines.extend(["## Scraping status and limitations", ""])
    for board in data.get("boards", []):
        status = f"{board.get('job_count', 0)} jobs captured"
        errors = board.get("errors") or []
        if errors:
            status += "; " + " ".join(str(error) for error in errors)
        lines.append(f"- **{board.get('source')}:** {status}")

    roles = search.get("roles", [])
    lines.extend(
        [
            "",
            "### Search queries used",
            "",
            ", ".join(roles) if roles else "Board default listings",
            "",
            "### Important limitations",
            "",
            "- Only boards that serve listings without a login or API key were used. Indeed, ZipRecruiter, "
            "Glassdoor, and LinkedIn all block automated access, so roles that appear only there are not covered here.",
            "- A live link is not a guarantee that the role remains open, and posted locations are not always "
            "where the work actually happens. Confirm both before applying.",
            "- No applications were submitted. This report only discovers and ranks public postings.",
            "",
            "## Re-run",
            "",
            "```bash",
            f"python3 -m job_scrapers.run_all '{data.get('resume', '')}' \\",
            f"  --location '{search.get('location', '')}' --work-model {work_model} \\",
            "  --output tmp/job-scrape-results.json --limit 10",
            "python3 generate_recommendations.py --input tmp/job-scrape-results.json --output job_recommendations.md",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("tmp/job-scrape-results.json"))
    parser.add_argument("--output", type=Path, default=Path("job_recommendations.md"))
    args = parser.parse_args()
    data = json.loads(args.input.expanduser().read_text(encoding="utf-8"))
    args.output.expanduser().write_text(render(data), encoding="utf-8")
    print(args.output.expanduser().resolve())


if __name__ == "__main__":
    main()
