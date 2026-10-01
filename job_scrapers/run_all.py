from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from .adzuna import scrape as scrape_adzuna
from .builtin import scrape as scrape_builtin
from .climatebase import scrape as scrape_climatebase
from .common import SearchPreferences, filter_by_salary, load_report, rank_jobs
from .dice import scrape as scrape_dice
from .remoteok import scrape as scrape_remoteok
from .talent import scrape as scrape_talent
from .weworkremotely import scrape as scrape_wwr
from .wellfound import scrape as scrape_wellfound
from .workable import scrape as scrape_workable
from .yc_jobs import scrape as scrape_yc


ROLE_QUERIES = {
    "events": (
        "event coordinator",
        "wedding coordinator",
        "event planner",
        "wedding planner",
        "venue coordinator",
        "catering sales manager",
        "event sales manager",
        "banquet manager",
        "meeting planner",
        "event manager",
    ),
    "technology": (
        "senior software engineer",
        "frontend engineer",
        "platform engineer",
        "site reliability engineer",
        "security engineer",
    ),
}


def collect_events(preferences: SearchPreferences, pages: int, detail_limit: int) -> List[Dict[str, Any]]:
    roles = list(preferences.roles)
    return [
        scrape_talent(roles, preferences.location, pages, detail_limit),
        scrape_adzuna(roles, preferences.location, preferences.radius_miles),
        scrape_workable(roles, preferences.location),
    ]


def collect_technology() -> List[Dict[str, Any]]:
    return [
        scrape_wellfound(50),
        scrape_builtin(50),
        scrape_dice(50),
        scrape_remoteok(150),
        scrape_yc(50),
        scrape_wwr(),
        scrape_climatebase(),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape public job boards and rank jobs against a resume.")
    parser.add_argument("resume", type=Path)
    parser.add_argument("--output", type=Path, default=Path("tmp/job-scrape-results.json"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--location", default="", help='Target metro, e.g. "Denver, CO"')
    parser.add_argument(
        "--work-model",
        default="any",
        choices=("onsite", "hybrid", "remote", "any"),
        help="Preferred working arrangement",
    )
    parser.add_argument("--radius", type=int, default=50, help="Commute radius in miles")
    parser.add_argument(
        "--min-salary",
        type=float,
        default=0,
        help="Annual salary floor; drops listings that cannot clear it, including unstated ones",
    )
    parser.add_argument("--role", action="append", default=[], help="Search query; repeatable")
    parser.add_argument("--domain", choices=sorted(ROLE_QUERIES), help="Override the auto-detected resume domain")
    parser.add_argument("--pages", type=int, default=2, help="Result pages to walk per search query")
    parser.add_argument(
        "--max-per-source",
        type=int,
        default=0,
        help="Cap recommendations per board (0 scales automatically with --limit)",
    )
    parser.add_argument(
        "--detail-limit", type=int, default=40, help="Listings to fetch full descriptions for"
    )
    args = parser.parse_args()

    report = load_report(str(args.resume), args.domain)
    roles = args.role or list(ROLE_QUERIES.get(report.domain, ()))
    preferences = SearchPreferences(
        location=args.location,
        work_model=args.work_model,
        radius_miles=args.radius,
        min_salary=args.min_salary,
        roles=tuple(roles),
    )

    payloads = (
        collect_events(preferences, args.pages, args.detail_limit)
        if report.domain == "events"
        else collect_technology()
    )
    jobs: List[Dict[str, Any]] = []
    for payload in payloads:
        jobs.extend(payload.get("jobs", []))
    scraped_count = len(jobs)
    jobs, dropped_below, dropped_unstated = filter_by_salary(jobs, args.min_salary)
    # Scores are not comparable across boards: Adzuna serves ~500 characters of description where
    # Talent.com serves ~2800, so a global ranking would order by feed richness. Take the best of
    # each source instead, letting one board fill at most half the shortlist.
    max_per_source = args.max_per_source or max(3, (args.limit + 1) // 2)
    ranked = rank_jobs(jobs, report, args.limit, max_per_source=max_per_source, preferences=preferences)

    payload = {
        "resume": str(args.resume.expanduser().resolve()),
        "candidate_name": report.candidate.get("name", ""),
        "domain": report.domain,
        "search": {
            "location": preferences.location,
            "work_model": preferences.work_model,
            "radius_miles": preferences.radius_miles,
            "min_salary": preferences.min_salary,
            "roles": list(roles),
        },
        "scraped_job_count": scraped_count,
        "salary_filter": {
            "min_salary": preferences.min_salary,
            "eligible": len(jobs),
            "dropped_below_floor": dropped_below,
            "dropped_unstated_salary": dropped_unstated,
        },
        "boards": [
            {"source": item.get("source"), "job_count": len(item.get("jobs", [])), "errors": item.get("errors", [])}
            for item in payloads
        ],
        "recommendations": ranked,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "scraped_job_count": scraped_count,
                "salary_eligible": len(jobs),
                "dropped_below_floor": dropped_below,
                "dropped_unstated_salary": dropped_unstated,
                "recommendations": len(ranked),
                "output": str(output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
