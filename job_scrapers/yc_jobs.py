from __future__ import annotations

import argparse
import re
from typing import List

from bs4 import BeautifulSoup

from .common import absolute, fetch, job, result, save_or_print


SOURCE = "Y Combinator Jobs"
LIST_URL = "https://www.ycombinator.com/jobs"
ROLE_RE = re.compile(r"engineer|developer|devops|platform|security|frontend|backend|full.?stack|sre|software|architect|infrastructure", re.I)


def scrape(limit: int = 35) -> dict:
    try:
        listing = fetch(LIST_URL)
        soup = BeautifulSoup(listing.text, "html.parser")
    except Exception as exc:
        return result(SOURCE, [], [f"listing fetch failed: {exc}"])

    links = []
    seen = set()
    for anchor in soup.select('a[href*="/companies/"][href*="/jobs/"]'):
        title = anchor.get_text(" ", strip=True)
        href = anchor.get("href", "").split("?")[0]
        if not href or href in seen or not title or not ROLE_RE.search(title):
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
            page_text = detail.get_text(" ", strip=True)
            title_node = detail.select_one("h1")
            title = title_node.get_text(" ", strip=True) if title_node else listing_title
            company_match = re.search(r"at (.+?)\s+\| Y Combinator", detail.title.get_text(" ", strip=True) if detail.title else "")
            salary_match = re.search(r"\$[\d,]+\s*[Kk]?\s*[–-]\s*\$[\d,]+\s*[Kk]?", page_text)
            jobs.append(
                job(
                    source=SOURCE,
                    title=title,
                    company=company_match.group(1) if company_match else "",
                    url=url,
                    description=page_text,
                    salary=salary_match.group(0) if salary_match else "",
                    metadata={"listing_url": LIST_URL},
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
