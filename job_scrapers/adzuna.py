from __future__ import annotations

import argparse
import os
from typing import Any, Dict, List, Sequence

from .common import clean_html, fetch, job, result, save_or_print


SOURCE = "Adzuna"
SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
MILES_TO_KM = 1.60934
MAX_RESULTS_PER_PAGE = 50

CREDENTIAL_HINT = (
    "Adzuna needs credentials. Register a free app at https://developer.adzuna.com/ and export "
    "ADZUNA_APP_ID and ADZUNA_APP_KEY before running."
)


def credentials() -> tuple[str, str]:
    return os.environ.get("ADZUNA_APP_ID", ""), os.environ.get("ADZUNA_APP_KEY", "")


def salary_of(record: Dict[str, Any]) -> str:
    low, high = record.get("salary_min"), record.get("salary_max")
    if not low and not high:
        return ""
    # Adzuna infers a range when the employer omits one; say so rather than implying it is posted.
    predicted = " (estimated by Adzuna)" if str(record.get("salary_is_predicted", "0")) == "1" else ""
    if low and high and low != high:
        return f"${low:,.0f}-${high:,.0f} per year{predicted}"
    return f"${(low or high):,.0f} per year{predicted}"


def scrape(
    roles: Sequence[str],
    location: str = "",
    radius_miles: int = 50,
    country: str = "us",
    results_per_page: int = 50,
    max_days_old: int = 60,
) -> dict:
    app_id, app_key = credentials()
    if not app_id or not app_key:
        return result(SOURCE, [], [CREDENTIAL_HINT])

    collected: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []

    for role in roles:
        params: Dict[str, Any] = {
            "app_id": app_id,
            "app_key": app_key,
            "what": role,
            "results_per_page": min(results_per_page, MAX_RESULTS_PER_PAGE),
            "max_days_old": max_days_old,
            "content-type": "application/json",
        }
        if location:
            params["where"] = location
            # Adzuna expresses the search radius in kilometres. This parameter is not listed in
            # their published docs, so a 400 triggers a retry without it rather than losing the query.
            params["distance"] = max(1, round(radius_miles * MILES_TO_KM))

        url = SEARCH_URL.format(country=country, page=1)
        try:
            payload = fetch(url, params=params).json()
        except Exception as exc:
            if "400" not in str(exc) or "distance" not in params:
                errors.append(f"{role}: {exc}")
                continue
            params.pop("distance")
            errors.append(f"{role}: retried without the distance filter after a 400 from Adzuna")
            try:
                payload = fetch(url, params=params).json()
            except Exception as retry_exc:
                errors.append(f"{role}: {retry_exc}")
                continue

        for record in payload.get("results", []):
            url = record.get("redirect_url") or ""
            if not url or url in collected:
                continue
            collected[url] = {
                "title": record.get("title", ""),
                "company": str((record.get("company") or {}).get("display_name", "")),
                "url": url,
                "description": clean_html(record.get("description", "")),
                "location": str((record.get("location") or {}).get("display_name", "")),
                "posted": record.get("created", ""),
                "salary": salary_of(record),
                "query": role,
                "category": str((record.get("category") or {}).get("label", "")),
                "contract_time": record.get("contract_time", ""),
                "contract_type": record.get("contract_type", ""),
            }

    jobs = [
        job(
            source=SOURCE,
            title=record["title"],
            company=record["company"],
            url=record["url"],
            description=record["description"],
            location=record["location"],
            posted=record["posted"],
            salary=record["salary"],
            metadata={
                "query": record["query"],
                "category": record["category"],
                "employment_type": " ".join(
                    part for part in (record["contract_time"], record["contract_type"]) if part
                ),
            },
        )
        for record in collected.values()
    ]
    return result(SOURCE, jobs, errors)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search Adzuna for jobs matching a role and location.")
    parser.add_argument("--output")
    parser.add_argument("--location", default="Denver, CO")
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--radius", type=int, default=50, help="Search radius in miles")
    parser.add_argument("--country", default="us")
    parser.add_argument("--max-days-old", type=int, default=60)
    args = parser.parse_args()
    roles = args.role or ["event coordinator"]
    save_or_print(
        scrape(roles, args.location, args.radius, args.country, max_days_old=args.max_days_old),
        args.output,
    )


if __name__ == "__main__":
    main()
