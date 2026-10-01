# jobSearch

Give it a resume PDF and it finds matching jobs. It reads the resume on your machine, works out what field the candidate is in, searches public job boards and ranks the listings by how well they fit the resume, the target location, the preferred work arrangement and an optional salary floor. The result is a Markdown report with links, pay, and a short note on why each job fits.

Nothing gets submitted anywhere. It only finds and ranks public postings.

## How it works

1. **Read the resume.** `resume_job_analyzer.py` pulls the text out of the PDF. It handles two-column layouts and spaced-out display type, then finds the name, headline, work history, skills and contact details.
2. **Detect the field.** The resume is classified as either `technology` or `events` (events, weddings, catering and hospitality). Each field has its own skill list, job types, search terms and job boards.
3. **Scrape and rank.** `job_scrapers/run_all.py` searches the boards for that field. It scores each listing on resume overlap, title relevance, seniority, location, work arrangement and salary.
4. **Write the report.** `generate_recommendations.py` turns the ranked results into a readable Markdown file.

### Job boards by field

| Field | Boards | Notes |
|---|---|---|
| `events` | Talent.com, Adzuna, Workable | Searches by role and location. Adzuna needs a free API key (see below) and is skipped without one. |
| `technology` | Built In, Wellfound, Y Combinator Jobs, Dice, Remote OK, We Work Remotely, Climatebase | Fixed remote-tech searches. We Work Remotely and Climatebase often block automated requests. |

Indeed, LinkedIn, Glassdoor and ZipRecruiter aren't covered. They block automated access, and getting around that would break their terms of service.

## Install

You need Python 3 (developed and tested on 3.14 on macOS).

```bash
git clone https://github.com/danlesko/jobSearch.git
cd jobSearch
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Optional: Adzuna API key

Adzuna adds a lot of listings for event and hospitality roles, and it publishes salary ranges more often than the other boards. The key is free:

1. Register an app at <https://developer.adzuna.com/>.
2. Create a file called `.env.local` in the repo root:

   ```bash
   ADZUNA_APP_ID=your_app_id
   ADZUNA_APP_KEY=your_app_key
   ```

The scrapers load this file automatically, and real environment variables take priority over it. `.env.local` is gitignored. Without a key, Adzuna is skipped and the report says so.

## Usage

Searching takes two commands. The first scrapes and ranks, the second writes the report:

```bash
python3 -m job_scrapers.run_all path/to/resume.pdf \
  --location "Denver, CO" --work-model onsite \
  --output tmp/results.json --limit 15

python3 generate_recommendations.py --input tmp/results.json --output job_recommendations.md
```

To check how a resume is being read before you search:

```bash
python3 resume_job_analyzer.py path/to/resume.pdf          # readable summary
python3 resume_job_analyzer.py path/to/resume.pdf --json   # full structured output
```

Add `--domain events` or `--domain technology` to either command if the field is detected wrong.

### Examples

In-person event roles around Denver:

```bash
python3 -m job_scrapers.run_all resume.pdf --location "Denver, CO" --work-model onsite --limit 15
```

Any work arrangement, but only listings that pay at least $70k:

```bash
python3 -m job_scrapers.run_all resume.pdf --location "Denver, CO" --work-model any \
  --min-salary 70000 --output tmp/flexible.json --limit 15
```

Remote software roles:

```bash
python3 -m job_scrapers.run_all resume.pdf --work-model remote --limit 10
```

Your own search terms instead of the defaults for the field:

```bash
python3 -m job_scrapers.run_all resume.pdf --location "Boulder, CO" \
  --role "venue manager" --role "wedding planner"
```

### `run_all` options

| Option | Default | What it does |
|---|---|---|
| `resume` | required | Path to the resume PDF. |
| `--location` | none | Target city, written as `"City, ST"` (for example `"Denver, CO"`). Jobs in that city score higher. For Denver and Columbus, nearby towns also count. For other cities, only the city name and state are checked. |
| `--work-model` | `any` | `onsite`, `hybrid`, `remote` or `any`. Matching listings score higher and conflicting ones lower. In an `onsite` search, hybrid jobs still get partial credit. |
| `--radius` | `50` | Search radius in miles. Only Adzuna uses it. |
| `--min-salary` | none | Yearly salary floor. A pay range counts if its top end clears the floor, and hourly rates are converted at 2,080 hours a year. **Listings that don't post a salary are dropped too**, and the report says how many. |
| `--role` | depends on field | A search term. Repeat the flag for more than one. Only the events boards use it. |
| `--limit` | `10` | Most jobs to include. The list can come back shorter, because weak matches are dropped instead of padding it out. |
| `--domain` | auto-detected | Set the field to `events` or `technology` yourself. |
| `--pages` | `2` | Talent.com result pages to read per search term. |
| `--detail-limit` | `40` | How many Talent.com listings to open for the full description. More is slower but more accurate. |
| `--max-per-source` | half of `--limit` | Most jobs from any one board. Boards return different amounts of description text, so their scores can't be compared directly and are capped separately. |
| `--output` | `tmp/job-scrape-results.json` | Where the ranked JSON goes. |

A full events run usually takes one to two minutes.

## Reading the report

Each job lists the company, board, work arrangement, location, pay, posting date, fit score, the resume terms it matched and any caveats. A few things to watch for:

- **Salaries marked "estimated by Adzuna"** are Adzuna's guess, not the employer's offer.
- **"Unclear" work arrangement** means the listing doesn't say. The tool won't assume on-site.
- **Aggregated listings** from Talent.com and Adzuna can be stale or posted by a staffing agency. Check the employer's own careers page before you apply.

## Privacy

The resume is read on your machine and never uploaded. The only network requests are job searches, plus the full listing pages fetched from Talent.com. Generated reports and scrape results contain the candidate's name, so `*job_recommendations*.md` and `tmp/` are gitignored. Keep them out of commits.

## Adding a field

To support another kind of job, add the following under the same key:

- a skill list, job types, field-detection keywords and title words in `resume_job_analyzer.py`
- default search terms in `ROLE_QUERIES` in `job_scrapers/run_all.py`
- the set of boards to search for that field
