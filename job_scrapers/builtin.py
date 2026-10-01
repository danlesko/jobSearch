from __future__ import annotations

import argparse
import re
from typing import List

from bs4 import BeautifulSoup

from .common import absolute, fetch, job, json_ld, location_text, result, save_or_print, schema_text


SOURCE = "Built In"
LIST_URL = "https://builtin.com/jobs/remote"
ROLE_RE = re.compile(r"engineer|developer|devops|platform|security|frontend|backend|full.?stack|sre|qa|software|architect|automation", re.I)


def scrape(limit: int = 35) -> dict:
    try:
        listing = fetch(LIST_URL)
        soup = BeautifulSoup(listing.text, "html.parser")
    except Exception as exc:
        return result(SOURCE, [], [f"listing fetch failed: {exc}"])

    links = []
    seen = set()
    for anchor in soup.select('a[href^="/job/"]'):
        title = anchor.get_text(" ", strip=True)
        href = anchor.get("href", "").split("?")[0]
        if not href or href in seen or not ROLE_RE.search(title):
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
            breadcrumb = [record for record in json_ld(detail) if record.get("@type") == "BreadcrumbList"]
            company = ""
            if breadcrumb:
                elements = breadcrumb[0].get("itemListElement", [])
                if elements:
                    company = elements[0].get("name", "")
            page_text = detail.get_text(" ", strip=True)
            jobs.append(
                job(
                    source=SOURCE,
                    title=posting.get("title") or listing_title,
                    company=company,
                    url=url,
                    description=(posting.get("description") or "") + " " + page_text,
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
