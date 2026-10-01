from __future__ import annotations

import argparse
import re
from typing import Any, Dict, List, Optional, Sequence

from bs4 import BeautifulSoup

from .common import absolute, fetch, job, result, save_or_print


SOURCE = "Talent.com"
LIST_URL = "https://www.talent.com/jobs"

# Searching "event" also surfaces recruiting fairs, which are not event-industry roles.
JOB_FAIR_RE = re.compile(
    r"hiring event|hiring fair|job fair|career fair|hiring day|open interview|walk[- ]in interview|"
    r"\(indeed event\)|recruit(?:ing|ment) event",
    re.I,
)
SALARY_RE = re.compile(r"Salary\s*(.+?)(?:\s*Job type|\s*$)", re.I)


def card_field(card: Any, prefix: str) -> str:
    """Talent.com hash-suffixes its class names, so match on the stable prefix."""
    node = card.select_one(f'[class^="{prefix}"]')
    return node.get_text(" ", strip=True) if node else ""


def detail_salary(soup: BeautifulSoup) -> str:
    node = soup.select_one('[class^="style_jobDetails__"]')
    if not node:
        return ""
    match = SALARY_RE.search(node.get_text(" ", strip=True))
    return match.group(1).strip() if match else ""


def scrape(
    roles: Sequence[str],
    location: str = "",
    pages: int = 2,
    detail_limit: int = 40,
) -> dict:
    collected: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []

    for role in roles:
        for page in range(1, pages + 1):
            params: Dict[str, Any] = {"k": role, "p": page}
            if location:
                params["l"] = location
            try:
                response = fetch(LIST_URL, params=params, timeout=30)
            except Exception as exc:
                errors.append(f"{role} p{page}: {exc}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            cards = soup.select('[data-testid="job-card-unified"]')
            if not cards:
                errors.append(f"{role} p{page}: no job cards found in markup")
                continue

            for card in cards:
                title = card_field(card, "JobCard_title__")
                anchor = card.select_one('a[href*="/view?id="]')
                if not title or not anchor or JOB_FAIR_RE.search(title):
                    continue
                url = absolute(LIST_URL, str(anchor.get("href", "")))
                if url in collected:
                    continue
                posted = card_field(card, "JobCard_timeText__")
                collected[url] = {
                    "title": title,
                    "company": card_field(card, "JobCard_company__"),
                    "url": url,
                    "location": card_field(card, "JobCard_location__"),
                    "description": card_field(card, "JobCard_snippet__"),
                    "posted": re.sub(r"^Last updated:\s*", "", posted, flags=re.I),
                    "query": role,
                }

    # Card snippets are truncated to ~210 characters, which is thin for resume matching, but
    # fetching every detail page is impolite. Spend the budget on the listings most likely to make
    # the shortlist — those whose title echoes the search terms — so enrichment is deterministic
    # rather than dependent on which query happened to return a listing first.
    query_words = {word for role in roles for word in re.findall(r"[a-z]+", role.lower())}

    def title_relevance(record: Dict[str, Any]) -> int:
        title_words = set(re.findall(r"[a-z]+", record["title"].lower()))
        return len(query_words & title_words)

    ordered = sorted(collected.values(), key=lambda record: -title_relevance(record))
    for record in ordered[:detail_limit]:
        try:
            detail = BeautifulSoup(fetch(record["url"], timeout=30).text, "html.parser")
        except Exception as exc:
            errors.append(f"{record['url']}: {exc}")
            continue
        body = detail.select_one('[class^="style_jobDescription__"]') or detail.select_one("article")
        if body:
            record["description"] = body.get_text(" ", strip=True)
        record["salary"] = detail_salary(detail)

    jobs = [
        job(
            source=SOURCE,
            title=record["title"],
            company=record["company"],
            url=record["url"],
            description=record["description"],
            location=record["location"],
            posted=record["posted"],
            salary=record.get("salary", ""),
            metadata={"query": record["query"]},
        )
        for record in collected.values()
    ]
    return result(SOURCE, jobs, errors)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--location", default="Denver, CO")
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--detail-limit", type=int, default=40)
    args = parser.parse_args()
    roles = args.role or ["event coordinator"]
    save_or_print(scrape(roles, args.location, args.pages, args.detail_limit), args.output)


if __name__ == "__main__":
    main()
