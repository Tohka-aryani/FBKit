# FBKit

CLI tool for batch-scraping Facebook post comments and replies via Facebook's unofficial GraphQL API.

## Features

- Batch scrape multiple posts from a URL list file
- Extract top-level comments with author names and reaction counts
- Extract direct replies to each comment
- JSON output per post under `simple_post/<post_id>/`
- Optional proxy support via `.env`

## Requirements

- Python 3.8+
- `requests`, `python-dotenv`

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

Output is written to `simple_post/<post_id>/<post_id>.json`.

## Output format

Each JSON file contains:

- `post_id`, `source_url`, `post_info`
- `comments[]` with `author`, `author_id`, `text`, `reaction_count`
- `replies[]` on each comment with the same fields plus `reply_id`

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
