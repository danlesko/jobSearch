from __future__ import annotations

import argparse
import re
from typing import List

from bs4 import BeautifulSoup

from .common import absolute, fetch, job, result, save_or_print


SOURCE = "Wellfound"
LIST_URL = "https://wellfound.com/jobs"
ROLE_RE = re.compile(r"engineer|developer|devops|platform|security|frontend|backend|full.?stack|sre|qa|software|architect", re.I)


def scrape(limit: int = 40) -> dict:
    errors: List[str] = []
    try:
        listing = fetch(LIST_URL)
        soup = BeautifulSoup(listing.text, "html.parser")
    except Exception as exc:
        return result(SOURCE, [], [f"listing fetch failed: {exc}"])

    links = []
    seen = set()
    for anchor in soup.select('a[href^="/jobs/"]'):
        href = anchor.get("href", "").split("?")[0]
        title = anchor.get_text(" ", strip=True)
        if not href or href in seen or not ROLE_RE.search(title):
            continue
        seen.add(href)
        links.append((title, absolute(LIST_URL, href)))
        if len(links) >= limit:
            break

    jobs = []
    for listing_title, url in links:
        try:
            response = fetch(url)
            detail = BeautifulSoup(response.text, "html.parser")
            title = detail.select_one("h1")
            title_text = title.get_text(" ", strip=True) if title else listing_title
            page_text = detail.get_text(" ", strip=True)
            match = re.search(r" at (.+?)\s+•", detail.title.get_text(" ", strip=True) if detail.title else "")
            company = match.group(1) if match else ""
            location_match = re.search(r"Job Location\s+(.+?)\s+(?:Visa Sponsorship|Relocation|About the job)", page_text)
            salary_match = re.search(r"(\$[\d,]+\s*[kK]?\s*[–-]\s*\$[\d,]+\s*[kK]?)", page_text)
            posted_match = re.search(r"Posted:\s*([^•]+)", page_text)
            jobs.append(
                job(
                    source=SOURCE,
                    title=title_text,
                    company=company,
                    url=url,
                    description=page_text,
                    location=location_match.group(1) if location_match else "",
                    posted=posted_match.group(1) if posted_match else "",
                    salary=salary_match.group(1) if salary_match else "",
                    metadata={"listing_url": LIST_URL},
                )
            )
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    return result(SOURCE, jobs, errors)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()
    save_or_print(scrape(args.limit), args.output)


if __name__ == "__main__":
    main()
