from __future__ import annotations

import argparse
import re
from typing import List

from .common import clean_html, fetch, job, result, save_or_print


SOURCE = "Remote OK"
API_URL = "https://remoteok.com/api"


def scrape(limit: int = 100) -> dict:
    try:
        response = fetch(API_URL)
        records = response.json()
    except Exception as exc:
        return result(SOURCE, [], [f"API fetch failed: {exc}"])

    jobs = []
    for record in records:
        if not isinstance(record, dict) or not record.get("position") or not record.get("url"):
            continue
        description = clean_html(record.get("description", ""))
        # Exclude obvious low-signal posts while retaining normal remote engineering roles.
        if re.search(r"please mention the word|tag [A-Za-z0-9_.-]+ when applying|data annotation", description, re.I):
            continue
        jobs.append(
            job(
                source=SOURCE,
                title=record.get("position", ""),
                company=record.get("company", ""),
                url=record.get("url", ""),
                description=description,
                location=record.get("location", ""),
                posted=record.get("date", ""),
                salary=record.get("salary", ""),
                tags=record.get("tags", []),
                metadata={"listing_url": API_URL, "id": record.get("id")},
            )
        )
        if len(jobs) >= limit:
            break
    errors = [] if jobs else ["No records survived the low-signal filter in the current public API response."]
    return result(SOURCE, jobs, errors)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    save_or_print(scrape(args.limit), args.output)


if __name__ == "__main__":
    main()
