from __future__ import annotations

import argparse
from typing import List

from bs4 import BeautifulSoup

from .common import absolute, fetch, job, json_ld, location_text, result, save_or_print, schema_text


SOURCE = "Dice"
LIST_URL = "https://www.dice.com/jobs?q=TypeScript%20Kubernetes%20React&location=Remote"


def scrape(limit: int = 35) -> dict:
    try:
        listing = fetch(LIST_URL)
        soup = BeautifulSoup(listing.text, "html.parser")
    except Exception as exc:
        return result(SOURCE, [], [f"listing fetch failed: {exc}"])

    links = []
    seen = set()
    for anchor in soup.select('a[href*="/job-detail/"]'):
        href = anchor.get("href", "").split("?")[0]
        title = anchor.get_text(" ", strip=True)
        if not href or href in seen or not title:
            continue
        seen.add(href)
        links.append((title, absolute(LIST_URL, href)))
        if len(links) >= limit:
            break

    jobs = []
    errors: List[str] = []
    for listing_title, url in links:
        try:
            response = fetch(url)
            detail = BeautifulSoup(response.text, "html.parser")
            posting = next((record for record in json_ld(detail) if record.get("@type") == "JobPosting"), {})
            page_text = detail.get_text(" ", strip=True)
            jobs.append(
                job(
                    source=SOURCE,
                    title=posting.get("title") or listing_title,
                    company=str(posting.get("hiringOrganization", {}).get("name", "")),
                    url=url,
                    description=posting.get("description") or page_text,
                    location=location_text(posting.get("jobLocation", "")),
                    posted=posting.get("datePosted", ""),
                    salary=schema_text(posting.get("baseSalary", "")),
                    metadata={"listing_url": LIST_URL, "employment_type": posting.get("employmentType", "")},
                )
            )
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    return result(SOURCE, jobs, errors)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--limit", type=int, default=35)
    args = parser.parse_args()
    save_or_print(scrape(args.limit), args.output)


if __name__ == "__main__":
    main()
