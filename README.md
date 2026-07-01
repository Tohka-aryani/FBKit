# FBKit

CLI tool for batch-scraping Facebook post comments and replies via Facebook's unofficial GraphQL API.

## Features

- Batch scrape multiple posts from a URL list file
- Extract top-level comments with author names and reaction counts
- Extract direct replies to each comment
- JSON output per batch run under `output/` with a timestamp filename
- Live terminal progress with elapsed time and ETA during scraping
- Optional proxy support via `.env`

## Requirements

- Python 3.8+
- `requests`, `python-dotenv`, `rich`

## Installation

```bash
git clone https://github.com/Tohka-aryani/FBKit.git
cd FBKit
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

## Usage

1. Copy the example URL file:

```bash
copy post_url.example.txt post_url.txt
```

2. Add one Facebook post URL per line to `post_url.txt`:

```
https://www.facebook.com/user/posts/pfbid...
```

3. Run the scraper:

```bash
python main.py
```

Output is written to `output/<YYYY-MM-DD HH-MM-SS>.json` (one combined file per run).

While scraping, the terminal shows live progress: current post (`1/2`), phase (resolving ID, fetching comments, fetching replies), elapsed time, and estimated time remaining. When the batch finishes, a per-post timing summary is printed.

## Output format

Each batch JSON file contains:

- `scraped_at` — human-readable run time (e.g. `2026-07-01 17:03:00`)
- `post_count`, `succeeded`, `failed`
- `posts[]` — each entry has `post_id`, `source_url`, `post_info`, and `comments[]`
- `failures[]` — optional list of `{url, error}` for URLs that could not be scraped

Each comment includes `author`, `author_id`, `text`, `reaction_count`, and `replies[]` (with `reply_id`, `author`, etc.).

## Optional proxy configuration

Create a `.env` file in the project root:

```
PROXY=http://username:password@proxy-server:port
STATIC_PROXY=http://username:password@proxy-server:port
```

## Notes

- Uses direct HTTP requests (no browser automation for scraping)
- Facebook GraphQL `doc_id` values may need periodic updates
- Scraping may violate Facebook's Terms of Service; use responsibly

## Attribution

Derived from [mohdtalal3/facebook_post_comment_scraper](https://github.com/mohdtalal3/facebook_post_comment_scraper).
