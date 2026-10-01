from __future__ import annotations

import argparse
from typing import Any, Dict, List, Sequence

from .common import clean_html, fetch, job, result, save_or_print


SOURCE = "Workable"
SEARCH_URL = "https://jobs.workable.com/api/v1/jobs"


def location_of(record: Dict[str, Any]) -> str:
    location = record.get("location") or {}
    parts = [location.get("city"), location.get("subregion") or location.get("region"), location.get("countryName")]
    text = ", ".join(str(part) for part in parts if part)
    if text:
        return text
    return "; ".join(str(item) for item in record.get("locations", []) if item)


def salary_of(record: Dict[str, Any]) -> str:
    salary = record.get("salary") or {}
    if isinstance(salary, dict) and salary.get("salaryFrom"):
        currency = salary.get("salaryCurrency", "")
        high = salary.get("salaryTo")
        low = salary.get("salaryFrom")
        return f"{currency} {low}-{high}".strip() if high else f"{currency} {low}".strip()
    return ""


def scrape(roles: Sequence[str], location: str = "", limit_per_role: int = 25) -> dict:
    jobs: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen: set[str] = set()

    for role in roles:
        params = {"query": role}
        if location:
            params["location"] = location
        try:
            payload = fetch(SEARCH_URL, params=params).json()
        except Exception as exc:
            errors.append(f"{role}: {exc}")
            continue

        for record in payload.get("jobs", [])[:limit_per_role]:
            url = record.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            jobs.append(
                job(
                    source=SOURCE,
                    title=record.get("title", ""),
                    company=str((record.get("company") or {}).get("title", "")),
                    url=url,
                    description=clean_html(record.get("description", "")),
                    location=location_of(record),
                    posted=record.get("created") or record.get("updated") or "",
                    salary=salary_of(record),
                    metadata={
                        "query": role,
                        "workplace": record.get("workplace", ""),
                        "employment_type": record.get("employmentType", ""),
                    },
                )
            )
    return result(SOURCE, jobs, errors)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--location", default="Denver, CO")
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    save_or_print(scrape(args.role or ["event coordinator"], args.location, args.limit), args.output)


if __name__ == "__main__":
    main()
