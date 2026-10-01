from __future__ import annotations

import argparse

from .common import fetch, result, save_or_print


SOURCE = "Climatebase"
URL = "https://climatebase.org/jobs"


def scrape() -> dict:
    try:
        response = fetch(URL)
        if "Just a moment" in response.text or response.status_code in (403, 429):
            return result(SOURCE, [], ["Public page returned a Cloudflare challenge; no bypass attempted."])
        return result(SOURCE, [], ["Page format was not recognized by the scraper."])
    except Exception as exc:
        return result(SOURCE, [], [f"access blocked or fetch failed: {exc}"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    save_or_print(scrape(), args.output)


if __name__ == "__main__":
    main()
